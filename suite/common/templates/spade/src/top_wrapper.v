// 端口契约包装层模板 (必需, 仅做命名适配, 无逻辑).
// Spade 生成: 模块 <工程名>::<实体名>, 输入端口 <名>_i, 全部输出打包在 output__.
// 下面以 fifo 案例为例 (顶层 sync_fifo, 实体 sync_fifo_impl, 工程名 fifo).
// output__ 位段顺序: 返回元组的第一个元素占最高位.
//   例如实体返回 (in_ready, out_valid, out_data<7:0>, count<4:0>, almost_full, almost_empty)
//   则 output__[16]=in_ready, [15]=out_valid, [14:7]=out_data, [6:2]=count, [1]=almost_full, [0]=almost_empty
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
