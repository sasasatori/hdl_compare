// matmul4x4: 4x4 int8 矩阵乘, C(int32) = A x B, 精确累加无饱和.
// 架构: S_IN 收 4 行 -> S_CALC 每拍算 1 个元素 (4 个乘法器, 16 拍) -> S_OUT 逐行发 4 拍.
// 末输入拍 -> 首输出拍延迟 = 18 拍 (<=32).
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

    localparam S_IN = 2'd0, S_CALC = 2'd1, S_OUT = 2'd2;
    reg [1:0] state;

    reg signed [7:0]  amat [0:3][0:3];  // amat[i][k]
    reg signed [7:0]  bmat [0:3][0:3];  // bmat[k][j] (按行收进来即 [k][j])
    reg signed [31:0] cmat [0:3][0:3];  // cmat[i][j]
    reg [1:0]         in_cnt;
    reg [1:0]         out_cnt;
    reg [3:0]         calc_cnt;         // 0..15, i=calc_cnt[3:2], j=calc_cnt[1:0]
    reg               out_valid_r;
    reg [127:0]       c_row_r;

    assign in_ready  = (state == S_IN);
    assign out_valid = out_valid_r;
    assign c_row     = c_row_r;

    wire accept = in_valid && in_ready;
    wire drain  = out_valid_r && out_ready;

    wire [1:0] ci = calc_cnt[3:2];
    wire [1:0] cj = calc_cnt[1:0];

    // 单元素点积: 4 个 8x8 乘法 + 3 级加法
    wire signed [15:0] p0 = amat[ci][0] * bmat[0][cj];
    wire signed [15:0] p1 = amat[ci][1] * bmat[1][cj];
    wire signed [15:0] p2 = amat[ci][2] * bmat[2][cj];
    wire signed [15:0] p3 = amat[ci][3] * bmat[3][cj];
    wire signed [31:0] dot = {{16{p0[15]}}, p0} + {{16{p1[15]}}, p1}
                           + {{16{p2[15]}}, p2} + {{16{p3[15]}}, p3};

    integer k;

    always @(posedge clk) begin
        if (rst) begin
            state       <= S_IN;
            in_cnt      <= 2'd0;
            out_cnt     <= 2'd0;
            calc_cnt    <= 4'd0;
            out_valid_r <= 1'b0;
        end else begin
            case (state)
                S_IN: begin
                    if (accept) begin
                        for (k = 0; k < 4; k = k + 1) begin
                            amat[in_cnt][k] <= a_row[8*k +: 8];
                            bmat[in_cnt][k] <= b_row[8*k +: 8];
                        end
                        if (in_cnt == 2'd3) begin
                            in_cnt   <= 2'd0;
                            calc_cnt <= 4'd0;
                            state    <= S_CALC;
                        end else begin
                            in_cnt <= in_cnt + 2'd1;
                        end
                    end
                end
                S_CALC: begin
                    cmat[ci][cj] <= dot;
                    if (calc_cnt == 4'd15) begin
                        out_cnt <= 2'd0;
                        state   <= S_OUT;
                    end else begin
                        calc_cnt <= calc_cnt + 4'd1;
                    end
                end
                S_OUT: begin
                    if (!out_valid_r) begin
                        // cmat 已就绪, 发第 0 行
                        c_row_r     <= {cmat[0][3], cmat[0][2], cmat[0][1], cmat[0][0]};
                        out_valid_r <= 1'b1;
                    end else if (drain) begin
                        if (out_cnt == 2'd3) begin
                            out_valid_r <= 1'b0;
                            out_cnt     <= 2'd0;
                            state       <= S_IN;
                        end else begin
                            out_cnt <= out_cnt + 2'd1;
                            case (out_cnt)
                                2'd0: c_row_r <= {cmat[1][3], cmat[1][2], cmat[1][1], cmat[1][0]};
                                2'd1: c_row_r <= {cmat[2][3], cmat[2][2], cmat[2][1], cmat[2][0]};
                                default: c_row_r <= {cmat[3][3], cmat[3][2], cmat[3][1], cmat[3][0]};
                            endcase
                        end
                    end
                end
                default: state <= S_IN;
            endcase
        end
    end

endmodule
