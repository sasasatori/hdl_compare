// sync_fifo (sv_v2): 直接实例化 svp_fifo 原语 (FWFT, 满时同拍推弹结构已固化)
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
    svp_fifo #(.DEPTH(16), .W(8), .AF_TH(12), .AE_TH(4), .CW(5)) u_fifo (
        .clk(clk), .rst(rst),
        .in_valid(in_valid), .in_ready(in_ready), .in_data(in_data),
        .out_valid(out_valid), .out_ready(out_ready), .out_data(out_data),
        .count(count), .almost_full(almost_full), .almost_empty(almost_empty)
    );
endmodule
