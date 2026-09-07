// fir16: 16 抽头 Q1.15 定点 FIR, 位精确 round-half-up + 饱和.
// 全并行 16 乘加, LAT=1; 背压时冻结整个数据通路.
module fir16 (
    input  wire        clk,
    input  wire        rst,
    input  wire        coef_we,
    input  wire [3:0]  coef_addr,
    input  wire [15:0] coef_data,
    input  wire        in_valid,
    output wire        in_ready,
    input  wire [15:0] in_data,
    output wire        out_valid,
    input  wire        out_ready,
    output wire [15:0] out_data
);

    reg signed [15:0] h [0:15];   // 系数
    reg signed [15:0] x [0:15];   // 样本历史, x[0] 最新
    reg               out_valid_r;
    reg signed [15:0] out_data_r;

    assign out_valid = out_valid_r;
    assign out_data  = out_data_r;

    // 背压: 输出未被接收时冻结
    wire stall  = out_valid_r && !out_ready;
    assign in_ready = !stall;
    wire accept = in_valid && in_ready;

    // 接受样本后的下一历史 (xn[0]=新样本)
    wire signed [15:0] xn [0:15];
    assign xn[0] = in_data;
    genvar gi;
    generate
        for (gi = 1; gi < 16; gi = gi + 1) begin : g_hist
            assign xn[gi] = x[gi-1];
        end
    endgenerate

    // 精确整数乘加 (36 bit 足够)
    reg signed [35:0] acc;
    integer k;
    always @* begin
        acc = 36'sd0;
        for (k = 0; k < 16; k = k + 1)
            acc = acc + h[k] * xn[k];
    end

    // round-half-up (对负数同样 +0x4000 后算术右移) + 饱和
    wire signed [35:0] acc_r = acc + 36'sh4000;
    wire signed [35:0] ys    = acc_r >>> 15;
    wire signed [15:0] y_sat = (ys > 36'sd32767)  ? 16'sd32767  :
                               (ys < -36'sd32768) ? -16'sd32768 :
                                                    ys[15:0];

    integer i;
    always @(posedge clk) begin
        if (rst) begin
            out_valid_r <= 1'b0;
            for (i = 0; i < 16; i = i + 1) begin
                h[i] <= 16'sd0;
                x[i] <= 16'sd0;
            end
        end else begin
            if (coef_we)
                h[coef_addr] <= coef_data;
            if (!stall) begin
                if (accept) begin
                    x[0] <= in_data;
                    for (i = 1; i < 16; i = i + 1)
                        x[i] <= x[i-1];
                    out_data_r  <= y_sat;
                    out_valid_r <= 1'b1;
                end else begin
                    out_valid_r <= 1'b0;
                end
            end
        end
    end

endmodule
