// sync_fifo: 深度16 位宽8 FWFT 同步 FIFO (参考实现, 用于套件自检)
module sync_fifo (
    input  wire       clk,
    input  wire       rst,
    input  wire       in_valid,
    output wire       in_ready,
    input  wire [7:0] in_data,
    output wire       out_valid,
    input  wire       out_ready,
    output wire [7:0] out_data,
    output reg  [4:0] count,
    output wire       almost_full,
    output wire       almost_empty
);
    reg [7:0] mem [0:15];
    reg [3:0] wr_ptr, rd_ptr;

    wire full  = (count == 5'd16);
    wire empty = (count == 5'd0);
    wire pop   = out_valid && out_ready;

    // 满且同拍弹出时允许继续写入 (SPEC: 满时同拍推弹)
    assign in_ready     = !full || pop;
    assign out_valid    = !empty;
    assign out_data     = mem[rd_ptr];
    assign almost_full  = (count >= 5'd12);
    assign almost_empty = (count <= 5'd4);

    wire push = in_valid && in_ready;

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            wr_ptr <= 4'd0;
            rd_ptr <= 4'd0;
            count  <= 5'd0;
        end else begin
            if (push) begin
                mem[wr_ptr] <= in_data;
                wr_ptr <= wr_ptr + 4'd1;
            end
            if (pop) begin
                rd_ptr <= rd_ptr + 4'd1;
            end
            case ({push, pop})
                2'b10:   count <= count + 5'd1;
                2'b01:   count <= count - 5'd1;
                default: count <= count;
            endcase
        end
    end
endmodule
