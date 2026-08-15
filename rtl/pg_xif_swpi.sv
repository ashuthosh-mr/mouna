// PARAGATO CV-X-IF coprocessor: post-increment store word.
//
//     pg.swpi rd, rs1, rs2     mem[rs1] <- rs2 ; rd <- rs1 + 4
//
// R-type, custom-0 space: funct7 = 0000000, funct3 = 001, opcode = 0001011.
// Used with rd == rs1 so the pointer advances in place, which is the shape of
// the `addi; add; sw` pattern that model/find_candidates.py ranks top on
// matmult-int (7,999 executions, ~5.9% of all cycles).
//
// Unlike a pure compute offload this needs the optional xif_mem interface: the
// coprocessor issues its own memory transaction and separately writes the
// updated pointer back to the register file. Sequence per instruction:
//
//   issue   accept, loadstore=1, writeback=1
//   mem     drive mem_valid with the address/data, wait for mem_ready
//   result  once mem_result_valid arrives, hand back rs1+4 and hold
//           result_valid until result_ready
//
// The registered result is deliberate: asserting result_valid combinationally
// hangs the core (the result is offered and withdrawn before it is observed).

module pg_xif_swpi
#(
  parameter int X_ID_WIDTH  = 4,
  parameter int X_MEM_WIDTH = 32
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

  localparam logic [6:0] OPCODE_CUSTOM0 = 7'b0001011;
  localparam logic [2:0] FUNCT3_SWPI    = 3'b001;
  localparam logic [6:0] FUNCT7_SWPI    = 7'b0000000;

  typedef enum logic [1:0] {IDLE, DO_MEM, WAIT_RES, DO_RESULT} state_e;
  state_e state, state_n;

  logic [31:0]           addr_q, data_q, instr;
  logic [4:0]            rd_q;
  logic [X_ID_WIDTH-1:0] id_q;
  logic                  is_swpi;

  assign instr   = xif_issue_if.issue_req.instr;
  assign is_swpi = xif_issue_if.issue_valid && (state == IDLE)
                   && (instr[6:0]   == OPCODE_CUSTOM0)
                   && (instr[14:12] == FUNCT3_SWPI)
                   && (instr[31:25] == FUNCT7_SWPI)
                   && (&xif_issue_if.issue_req.rs_valid[1:0]);

  // ----------------------------------------------------------------- issue --
  assign xif_issue_if.issue_ready          = (state == IDLE);
  assign xif_issue_if.issue_resp.accept    = is_swpi;
  assign xif_issue_if.issue_resp.writeback = is_swpi;   // updated pointer -> rd
  assign xif_issue_if.issue_resp.loadstore = is_swpi;   // uses xif_mem
  assign xif_issue_if.issue_resp.dualwrite = 1'b0;
  assign xif_issue_if.issue_resp.dualread  = 1'b0;
  assign xif_issue_if.issue_resp.ecswrite  = 1'b0;
  assign xif_issue_if.issue_resp.exc       = 1'b0;

  // ------------------------------------------------------------------- FSM --
  always_comb begin
    state_n = state;
    unique case (state)
      IDLE:      if (is_swpi)                       state_n = DO_MEM;
      DO_MEM:    if (xif_mem_if.mem_ready)          state_n = WAIT_RES;
      WAIT_RES:  if (xif_mem_result_if.mem_result_valid
                     && (xif_mem_result_if.mem_result.id == id_q))
                                                    state_n = DO_RESULT;
      DO_RESULT: if (xif_result_if.result_ready)    state_n = IDLE;
      default:                                      state_n = IDLE;
    endcase
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state  <= IDLE;
      addr_q <= '0;
      data_q <= '0;
      rd_q   <= '0;
      id_q   <= '0;
    end else begin
      state <= state_n;
      if (is_swpi) begin
        addr_q <= xif_issue_if.issue_req.rs[0];   // rs1: base pointer
        data_q <= xif_issue_if.issue_req.rs[1];   // rs2: value to store
        rd_q   <= instr[11:7];
        id_q   <= xif_issue_if.issue_req.id;
      end
    end
  end

  // ------------------------------------------------------------------- mem --
  assign xif_mem_if.mem_valid      = (state == DO_MEM);
  assign xif_mem_if.mem_req.id     = id_q;
  assign xif_mem_if.mem_req.addr   = addr_q;
  assign xif_mem_if.mem_req.mode   = 2'b11;   // machine mode
  assign xif_mem_if.mem_req.we     = 1'b1;
  assign xif_mem_if.mem_req.size   = 2'b10;   // word
  assign xif_mem_if.mem_req.wdata  = data_q;
  assign xif_mem_if.mem_req.last   = 1'b1;
  assign xif_mem_if.mem_req.spec   = 1'b0;

  // ---------------------------------------------------------------- result --
  assign xif_result_if.result_valid   = (state == DO_RESULT);
  assign xif_result_if.result.id      = id_q;
  assign xif_result_if.result.data    = addr_q + 32'd4;   // post-increment
  assign xif_result_if.result.rd      = rd_q;
  assign xif_result_if.result.we      = 1'b1;
  assign xif_result_if.result.ecsdata = '0;
  assign xif_result_if.result.ecswe   = '0;
  assign xif_result_if.result.exc     = 1'b0;
  assign xif_result_if.result.exccode = '0;

  // ------------------------------------------------ unused sub-interfaces --
  assign xif_compressed_if.compressed_ready       = 1'b1;
  assign xif_compressed_if.compressed_resp.instr  = '0;
  assign xif_compressed_if.compressed_resp.accept = 1'b0;

endmodule
