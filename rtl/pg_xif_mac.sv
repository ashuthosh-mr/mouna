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
// Timing: the multiply-add is done combinationally and the result is offered in
// the same cycle the instruction is accepted, so the instruction retires in a
// single cycle -- which is what the cycle model assumes when it scores a fused
// candidate at 1 cycle.

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

  assign instr  = xif_issue_if.issue_req.instr;
  assign is_mac = xif_issue_if.issue_valid
                  && (instr[6:0]   == OPCODE_CUSTOM0)
                  && (instr[14:12] == FUNCT3_MAC)
                  && (instr[26:25] == FUNCT2_MAC)
                  // all three source operands must be available
                  && (&xif_issue_if.issue_req.rs_valid[2:0]);

  // ----------------------------------------------------------------- issue --
  // Accept combinationally; nothing here can stall.
  assign xif_issue_if.issue_ready              = 1'b1;
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
  assign xif_result_if.result_valid   = is_mac;
  assign xif_result_if.result.id      = xif_issue_if.issue_req.id;
  assign xif_result_if.result.data    = sum;
  assign xif_result_if.result.rd      = instr[11:7];
  assign xif_result_if.result.we      = is_mac;
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
