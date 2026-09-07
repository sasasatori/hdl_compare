// fir16 (sv_v2): 16 抽头 Q1.15 FIR, 基于 SVP 原语:
// 16 乘积 -> svp_add_tree #(16,32) (4 级平衡树) -> svp_rnd_sat (round-half-up+饱和).
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

    // 16 个有符号乘积 (16x16 -> 32), 含当前输入的组合视图
    wire signed [16*32-1:0] pflat;
    genvar gi;
    generate
        for (gi = 0; gi < 16; gi = gi + 1) begin : g_prod
            assign pflat[gi*32 +: 32] = coef[gi] * ((gi == 0) ? $signed(in_data) : hist[gi-1]);
        end
    endgenerate

    // 平衡加法树 -> 36bit 精确和
    wire signed [35:0] acc;
    svp_add_tree #(.N(16), .W(32)) u_tree (.in_flat(pflat), .out(acc));

    // round-half-up + 饱和到 Q1.15
    wire signed [15:0] y_sat;
    svp_rnd_sat #(.IW(36), .OW(16), .FRAC(15)) u_rs (.in(acc), .out(y_sat));

    assign in_ready = (~out_valid) | out_ready;
    wire push = in_valid && in_ready;
    wire pop  = out_valid && out_ready;

    integer isq;
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
