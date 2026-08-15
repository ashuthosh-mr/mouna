// PARAGATO CV-X-IF coprocessor: fused multiply-accumulate.
//
// Implements one custom instruction, pg.mac:
//
//     pg.mac rd, rs1, rs2, rs3     rd <- rs3 + (rs1 * rs2)
//
// encoded as R4-type in the RISC-V custom-0 space:
//     rs3 = instr[31:27], funct2 = 00, funct3 = 000, opcode = 0001011
//
// R4-type matters: CV-X-IF sources its third operand from instr[31:27], so the
// accumulator has to be encoded there. It is NOT read back from rd.
//
// This is the top-ranked compute-only candidate reported by
// model/find_candidates.py on Embench matmult-int -- the `mul; add` pair whose
// product dies immediately, i.e. a multiply-accumulate.
//
// It needs three register-file sources (rs1, rs2 and rd read as the
// accumulator), so the core must be configured with X_NUM_RS = 3.
//
// Protocol: the multiply-add itself is combinational, but the result must be
// *registered* and held until the core acknowledges it with result_ready.
// Asserting result_valid combinationally in the same cycle as issue_valid
// offers and withdraws the result in one cycle, the core never observes the
// offload completing, and the pipeline stalls forever. Only one offloaded
// instruction is in flight at a time, which is enough for a single-cycle op.

module pg_xif_mac
  import cv32e40x_pkg::*;
#(
  parameter int X_NUM_RS    = 3,
  parameter int X_ID_WIDTH  = 4,
  parameter int X_RFR_WIDTH = 32,
  parameter int X_RFW_WIDTH = 32
)
(
  input  logic clk_i,
  input  logic rst_ni,
  if_xif.coproc_compressed xif_compressed_if,
  if_xif.coproc_issue      xif_issue_if,
  if_xif.coproc_commit     xif_commit_if,
  if_xif.coproc_mem        xif_mem_if,
  if_xif.coproc_mem_result xif_mem_result_if,
  if_xif.coproc_result     xif_result_if
);

  // ---------------------------------------------------------------- decode --
  localparam logic [6:0] OPCODE_CUSTOM0 = 7'b0001011;
  localparam logic [2:0] FUNCT3_MAC     = 3'b000;
  localparam logic [1:0] FUNCT2_MAC     = 2'b00;

  logic [31:0] instr;
  logic        is_mac;

  // Result-holding registers (declared here: is_mac and issue_ready depend on
  // res_pending, so it must exist before those assignments).
  logic                   res_pending;
  logic [31:0]            res_data;
  logic [4:0]             res_rd;
  logic [X_ID_WIDTH-1:0]  res_id;

  assign instr  = xif_issue_if.issue_req.instr;
  assign is_mac = xif_issue_if.issue_valid && !res_pending
                  && (instr[6:0]   == OPCODE_CUSTOM0)
                  && (instr[14:12] == FUNCT3_MAC)
                  && (instr[26:25] == FUNCT2_MAC)
                  // all three source operands must be available
                  && (&xif_issue_if.issue_req.rs_valid[2:0]);

  // ----------------------------------------------------------------- issue --
  // Refuse new work while a result is still waiting to be accepted.
  assign xif_issue_if.issue_ready              = !res_pending;
  assign xif_issue_if.issue_resp.accept        = is_mac;
  assign xif_issue_if.issue_resp.writeback     = is_mac;
  assign xif_issue_if.issue_resp.dualwrite     = 1'b0;
  assign xif_issue_if.issue_resp.dualread      = 1'b0;
  assign xif_issue_if.issue_resp.loadstore     = 1'b0;
  assign xif_issue_if.issue_resp.ecswrite      = 1'b0;
  assign xif_issue_if.issue_resp.exc           = 1'b0;

  // --------------------------------------------------------------- compute --
  // rs[0] = rs1, rs[1] = rs2, rs[2] = rd read back as the accumulator.
  logic [31:0] product, sum;
  assign product = xif_issue_if.issue_req.rs[0] * xif_issue_if.issue_req.rs[1];
  assign sum     = xif_issue_if.issue_req.rs[2] + product;

  // ---------------------------------------------------------------- result --
  // Capture on accept, then hold result_valid until result_ready handshakes.
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      res_pending <= 1'b0;
      res_data    <= '0;
      res_rd      <= '0;
      res_id      <= '0;
    end else if (is_mac) begin
      res_pending <= 1'b1;
      res_data    <= sum;
      res_rd      <= instr[11:7];
      res_id      <= xif_issue_if.issue_req.id;
    end else if (res_pending && xif_result_if.result_ready) begin
      res_pending <= 1'b0;
    end else if (res_pending && xif_commit_if.commit_valid
                 && xif_commit_if.commit.commit_kill
                 && (xif_commit_if.commit.id == res_id)) begin
      res_pending <= 1'b0;   // speculative instruction was killed
    end
  end

  assign xif_result_if.result_valid   = res_pending;
  assign xif_result_if.result.id      = res_id;
  assign xif_result_if.result.data    = res_data;
  assign xif_result_if.result.rd      = res_rd;
  assign xif_result_if.result.we      = 1'b1;
  assign xif_result_if.result.ecsdata = '0;
  assign xif_result_if.result.ecswe   = '0;
  assign xif_result_if.result.exc     = 1'b0;
  assign xif_result_if.result.exccode = '0;

  // ------------------------------------------------ unused sub-interfaces --
  // No compressed custom encodings.
  assign xif_compressed_if.compressed_ready      = 1'b1;
  assign xif_compressed_if.compressed_resp.instr = '0;
  assign xif_compressed_if.compressed_resp.accept = 1'b0;

  // No memory offload: this coprocessor never issues memory transactions.
  assign xif_mem_if.mem_valid       = 1'b0;
  assign xif_mem_if.mem_req         = '0;

endmodule
