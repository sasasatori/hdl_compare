`default_nettype wire
module sync_fifo (
    input  wire       clk,
    input  wire       rst,
    input  wire       in_valid,
    output wire       in_ready,
    input  wire [7:0] in_data,
    output wire       out_valid,
    input  wire       out_ready,
    output wire [7:0] out_data,
    output wire [4:0] count,
    output wire       almost_full,
    output wire       almost_empty
);
    wire [16:0] o;
    \fifo::sync_fifo_impl u_impl (
        .clk_i      (clk),
        .rst_i      (rst),
        .in_valid_i (in_valid),
        .in_data_i  (in_data),
        .out_ready_i(out_ready),
        .output__   (o)
    );
    assign in_ready     = o[16];
    assign out_valid    = o[15];
    assign out_data     = o[14:7];
    assign count        = o[6:2];
    assign almost_full  = o[1];
    assign almost_empty = o[0];
endmodule
