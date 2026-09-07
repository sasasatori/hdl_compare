// fir16: 16 抽头 Q1.15 FIR (参考实现, 套件自检用)
// 直接型: 输入移位寄存器 + 组合乘加 + 输出寄存器. 位精确语义见 SPEC.
module fir16 (
    input  wire        clk,
    input  wire        rst,
    input  wire        coef_we,
    input  wire [3:0]  coef_addr,
    input  wire [15:0] coef_data,
    input  wire        in_valid,
    output wire        in_ready,
    input  wire [15:0] in_data,
    output reg         out_valid,
    input  wire        out_ready,
    output reg  [15:0] out_data
);
    reg signed [15:0] coef [0:15];
    reg signed [15:0] hist [0:15];

    integer ic;   // 组合循环变量
    integer isq;  // 时序循环变量 (分开避免多驱动)
    reg signed [15:0] hist_n [0:15];
    reg signed [47:0] acc, acc_r, y48;
    reg signed [15:0] y_sat;

    always_comb begin
        hist_n[0] = in_data;
        for (ic = 1; ic < 16; ic = ic + 1) hist_n[ic] = hist[ic-1];
        acc = 48'sd0;
        for (ic = 0; ic < 16; ic = ic + 1) acc = acc + coef[ic] * hist_n[ic];
        acc_r = acc + 48'sh4000;
        y48   = acc_r >>> 15;
        if (y48 > 48'sd32767)       y_sat = 16'sd32767;
        else if (y48 < -48'sd32768) y_sat = -16'sd32768;
        else                        y_sat = y48[15:0];
    end

    // 1 级输出缓冲: 输出寄存器将被消费(或为空)时可收新样本
    assign in_ready = (~out_valid) | out_ready;

    wire push = in_valid && in_ready;
    wire pop  = out_valid && out_ready;

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            for (isq = 0; isq < 16; isq = isq + 1) begin
                coef[isq] <= 16'sd0;
                hist[isq] <= 16'sd0;
            end
            out_valid <= 1'b0;
            out_data  <= 16'sd0;
        end else begin
            if (coef_we) coef[coef_addr] <= coef_data;
            if (push) begin
                for (isq = 1; isq < 16; isq = isq + 1) hist[isq] <= hist[isq-1];
                hist[0]   <= in_data;
                out_data  <= y_sat;
                out_valid <= 1'b1;
            end else if (pop) begin
                out_valid <= 1'b0;
            end
        end
    end
endmodule
