// matmul4x4 (sv_v2): 迭代式 4 乘法器架构 (面积最优) + svp_add_tree 求和.
// 使能扇出修复: C 寄存器逐元素写 (每条使能仅 32 负载), 杜绝单使能驱动 128 DFF 的坏网.
module matmul4x4 (
    input  wire         clk,
    input  wire         rst,
    input  wire         in_valid,
    output wire         in_ready,
    input  wire [31:0]  a_row,
    input  wire [31:0]  b_row,
    output reg          out_valid,
    input  wire         out_ready,
    output wire [127:0] c_row
);
    localparam S_IN = 2'd0, S_CALC = 2'd1, S_OUT = 2'd2;
    reg [1:0]  st;
    reg [1:0]  beat;   // 输入拍 0..3
    reg [3:0]  elem;   // CALC 元素 0..15 (elem = {i[3:2], j[1:0]}, 行主序)
    reg [1:0]  orow;

    reg signed [31:0] areg [0:3];   // A 行 (行主序, byte k = A[i][k])
    reg signed [31:0] breg [0:3];   // B 行 (byte j = B[k][j])
    reg signed [31:0] creg [0:15];  // C (行主序)

    assign in_ready = (st == S_IN);
    wire push = in_valid && in_ready;
    wire pop  = out_valid && out_ready;

    // 当前元素操作数: C[i][j] = sum_k A[i][k]*B[k][j]
    wire [1:0] ci = elem[3:2];
    wire [1:0] cj = elem[1:0];
    wire signed [7:0] a0 = areg[ci][7:0];
    wire signed [7:0] a1 = areg[ci][15:8];
    wire signed [7:0] a2 = areg[ci][23:16];
    wire signed [7:0] a3 = areg[ci][31:24];
    wire signed [7:0] b0 = breg[0][8*cj +: 8];
    wire signed [7:0] b1 = breg[1][8*cj +: 8];
    wire signed [7:0] b2 = breg[2][8*cj +: 8];
    wire signed [7:0] b3 = breg[3][8*cj +: 8];

    wire signed [31:0] p0 = a0 * b0;
    wire signed [31:0] p1 = a1 * b1;
    wire signed [31:0] p2 = a2 * b2;
    wire signed [31:0] p3 = a3 * b3;

    wire signed [33:0] csum;
    svp_add_tree #(.N(4), .W(32)) u_csum (.in_flat({p3, p2, p1, p0}), .out(csum));

    // c_row 组合输出 (orow 行拼接), 与 out_valid 同拍生效, 消除首行错位
    assign c_row = {creg[orow*4+3], creg[orow*4+2], creg[orow*4+1], creg[orow*4]};

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            st <= S_IN; beat <= 0; elem <= 0; orow <= 0;
            out_valid <= 0;
        end else begin
            case (st)
                S_IN: begin
                    if (push) begin
                        areg[beat] <= a_row;
                        breg[beat] <= b_row;
                        if (beat == 2'd3) begin
                            st   <= S_CALC;
                            elem <= 0;
                        end else begin
                            beat <= beat + 1;
                        end
                    end
                end
                S_CALC: begin
                    creg[elem] <= csum[31:0];   // 逐元素写: 使能仅驱动 32 个 DFF
                    if (elem == 4'd15) begin
                        st        <= S_OUT;
                        orow      <= 0;
                        out_valid <= 1;
                    end else begin
                        elem <= elem + 1;
                    end
                end
                S_OUT: begin
                    if (pop) begin
                        if (orow == 2'd3) begin
                            st        <= S_IN;
                            beat      <= 0;
                            out_valid <= 0;
                        end else begin
                            orow <= orow + 1;
                        end
                    end
                end
                default: st <= S_IN;
            endcase
        end
    end
endmodule
