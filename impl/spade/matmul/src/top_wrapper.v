`default_nettype wire
module matmul4x4 (
    input  wire         clk,
    input  wire         rst,
    input  wire         in_valid,
    output wire         in_ready,
    input  wire [31:0]  a_row,
    input  wire [31:0]  b_row,
    output wire         out_valid,
    input  wire         out_ready,
    output wire [127:0] c_row
);
    wire [129:0] o;
    \matmul::matmul4x4_impl u_impl (
        .clk_i      (clk),
        .rst_i      (rst),
        .in_valid_i (in_valid),
        .a_row_i    (a_row),
        .b_row_i    (b_row),
        .out_ready_i(out_ready),
        .output__   (o)
    );
    assign in_ready  = o[129];
    assign out_valid = o[128];
    assign c_row     = o[127:0];
endmodule
