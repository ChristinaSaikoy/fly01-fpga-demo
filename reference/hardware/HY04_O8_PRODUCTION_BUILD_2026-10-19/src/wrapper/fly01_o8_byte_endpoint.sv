`timescale 1ns/1ps
// Single science owner: only this UART command engine accesses the unchanged O7 endpoint.
// Debug JTAG receives separate read-only mirrors; it cannot reset/commit/consume this state.
module fly01_o8_byte_endpoint #(
 parameter integer PACKET_TIMEOUT_CYCLES=5000000,
 parameter integer UART_BAUD=2000000
)(
 input logic clk,reset_n,
 input logic [7:0] rx_byte,input logic rx_valid,rx_error,rx_break,
 output logic [7:0] tx_byte,output logic tx_valid,input logic tx_ready,
 output logic [31:0] debug_generation,debug_next_frame,debug_session,debug_errors,
 output logic debug_pending,output logic [3:0] debug_fsm,output logic debug_error
);
 localparam integer MAX_RAW=2148;
 localparam [31:0] E_FORMAT=32'hE1,E_CRC=32'hE2,E_SESSION=32'hE3,E_ID=32'hE4,
   E_PENDING=32'hE5,E_COMMAND=32'hE6,E_PHY=32'hE7,E_BUSY=32'hE8,E_INNER=32'hE9;
 typedef enum logic [4:0] {IDLE,DISPATCH,FETCH_SET,FETCH_WAIT,FETCH_GET,
   WRITE_ADDR,WRITE_RESP,RESET_WAIT,READ_ADDR,READ_RESP,RESPOND,
   TX_START,TX_START_WAIT,TX_PREP,TX_RAW,TX_WAIT,TX_ESCAPE,TX_ESCAPE_WAIT,
   TX_END,TX_END_WAIT} state_t;
 state_t state;
 (* ram_style="block" *) logic [7:0] rx_ram[0:MAX_RAW-1];
 (* ram_style="block" *) logic [31:0] snapshots[0:529];
 (* ram_style="block" *) logic [31:0] last_request[0:303];
 logic [31:0] previous_request_word;
 logic [9:0] cached_request_words;
 logic comparing_retry;
 logic [7:0] rx_ram_data;
 logic [11:0] rx_read_address,rx_count,packet_length;
 logic in_frame,escaped,bad_frame,packet_ready;
 logic [31:0] rx_crc,rx_timer,rx_errors,control_errors,packet_error;
 logic [7:0] command,view,magic,version;
 logic [31:0] session,generation,frame;
 logic [31:0] inner_generation,inner_frame;
 logic [15:0] payload_length,reserved;
 wire [7:0] decoded_rx=escaped ? rx_byte^8'h20 : rx_byte;
 logic [12:0] axi_address;
 logic [31:0] axi_data,axi_rdata;
 logic aw_done,w_done,axi_awready,axi_wready,axi_bvalid,axi_arready,axi_rvalid;
 logic [1:0] axi_bresp,axi_rresp;
 wire axi_awvalid=state==WRITE_ADDR && !aw_done;
 wire axi_wvalid=state==WRITE_ADDR && !w_done;
 wire axi_bready=state==WRITE_RESP;
 wire axi_arvalid=state==READ_ADDR;
 wire axi_rready=state==READ_RESP;
 logic [9:0] word_index,word_count;
 logic [1:0] fetch_byte;
 logic [31:0] fetched_word,operation_guard;
 logic [9:0] reset_wait_count;
 // read_role: 0 poll core, 1 capture result, 2 generation after reset, 3 error.
 logic [1:0] read_role;
 logic have_cache;
 logic [31:0] cached_frame,cached_generation,response_status;
 logic [7:0] response_command,response_view;
 logic [31:0] response_session,response_generation,response_frame;
 logic [15:0] response_length;
 logic [11:0] tx_cursor;
 logic [31:0] tx_crc;
 logic [7:0] raw_hold;
 logic [9:0] snapshot_address;
 logic [31:0] snapshot_data;
 wire [11:0] response_offset=tx_cursor-20;
 wire [11:0] snapshot_offset=response_offset-4;
 wire sending_snapshot=(response_command==8'h84 || response_command==8'h85) && response_status==0;
 assign snapshot_address=sending_snapshot && response_offset>=4 && response_offset<response_length ?
     (response_view==1 ? 10'd471 : 10'd0)+(snapshot_offset>>2) : 10'd0;
 always_ff @(posedge clk) begin
   rx_ram_data<=rx_ram[rx_read_address];
   snapshot_data<=snapshots[snapshot_address];
   previous_request_word<=last_request[word_index];
 end
 function automatic [31:0] crc_byte(input [31:0] prior,input [7:0] value);
   reg [31:0] c;integer bitn;
   begin c=prior^{24'd0,value};for(bitn=0;bitn<8;bitn=bitn+1)c=c[0]?(c>>1)^32'hEDB88320:c>>1;crc_byte=c;end
 endfunction
 assign debug_errors=rx_errors+control_errors;
 fly01_o7_endpoint u_o7(
   .aclk(clk),.aresetn(reset_n),.s_axi_awaddr(axi_address),.s_axi_awprot(3'd0),
   .s_axi_awvalid(axi_awvalid),.s_axi_awready(axi_awready),
   .s_axi_wdata(axi_data),.s_axi_wstrb(4'hF),.s_axi_wvalid(axi_wvalid),.s_axi_wready(axi_wready),
   .s_axi_bresp(axi_bresp),.s_axi_bvalid(axi_bvalid),.s_axi_bready(axi_bready),
   .s_axi_araddr(axi_address),.s_axi_arprot(3'd0),.s_axi_arvalid(axi_arvalid),.s_axi_arready(axi_arready),
   .s_axi_rdata(axi_rdata),.s_axi_rresp(axi_rresp),.s_axi_rvalid(axi_rvalid),.s_axi_rready(axi_rready),
   .debug_fsm(debug_fsm),.debug_error(debug_error)
 );
 // Delimiter always re-synchronizes; malformed/oversize/half frames cannot reach AXI.
 // Completed RX buffer remains owned by command engine through the entire response.
 always_ff @(posedge clk)begin
   if(!reset_n)begin
     rx_count<=0;packet_length<=0;in_frame<=0;escaped<=0;bad_frame<=0;packet_ready<=0;
     rx_crc<=32'hFFFFFFFF;rx_timer<=0;rx_errors<=0;packet_error<=0;
     command<=0;view<=0;magic<=0;version<=0;session<=0;generation<=0;frame<=0;payload_length<=0;reserved<=0;
     inner_generation<=0;inner_frame<=0;
   end else begin
     if(state!=IDLE)packet_ready<=0;
     if(state==IDLE && !packet_ready)begin
       if(in_frame && rx_count!=0 && !rx_valid)begin
         rx_timer<=rx_timer+1;
         if(rx_timer>=PACKET_TIMEOUT_CYCLES-1)begin
           rx_errors<=rx_errors+1;packet_error<=E_PHY;packet_ready<=1;packet_length<=0;
           in_frame<=0;rx_count<=0;escaped<=0;bad_frame<=0;rx_timer<=0;
         end
       end
       if(rx_error || rx_break)begin
         rx_errors<=rx_errors+1;packet_error<=E_PHY;packet_ready<=1;packet_length<=0;
         in_frame<=0;rx_count<=0;escaped<=0;bad_frame<=0;rx_timer<=0;
       end else if(rx_valid)begin
         rx_timer<=0;
         if(rx_byte==8'h7E)begin
           if(in_frame && rx_count!=0)begin
             packet_ready<=1;packet_length<=rx_count;
             if(bad_frame || escaped || rx_count<24 || magic!=8'hF8 || version!=1 || reserved!=0 ||
                payload_length>2124 || rx_count!=24+payload_length)begin packet_error<=E_FORMAT;rx_errors<=rx_errors+1;end
             else if(rx_crc!=32'hDEBB20E3)begin packet_error<=E_CRC;rx_errors<=rx_errors+1;end
             else packet_error<=0;
           end
           rx_count<=0;rx_crc<=32'hFFFFFFFF;escaped<=0;bad_frame<=0;
           // Distinct start/end delimiters: closing a nonempty frame leaves RX outside.
           // Garbage between completed packets cannot consume the next command's opening.
           in_frame<=!(in_frame && rx_count!=0);
         end else if(in_frame)begin
           if(!escaped && rx_byte==8'h7D)escaped<=1;
           else begin
             escaped<=0;
             if(escaped && decoded_rx!=8'h7E && decoded_rx!=8'h7D)bad_frame<=1;
             if(rx_count>=MAX_RAW)bad_frame<=1;
             else begin
               rx_ram[rx_count]<=decoded_rx;rx_count<=rx_count+1;
               rx_crc<=crc_byte(rx_crc,decoded_rx);
               case(rx_count)
                 0:magic<=decoded_rx;1:version<=decoded_rx;2:command<=decoded_rx;3:view<=decoded_rx;
                 4,5,6,7:session[(rx_count-4)*8+:8]<=decoded_rx;
                 8,9,10,11:generation[(rx_count-8)*8+:8]<=decoded_rx;
                 12,13,14,15:frame[(rx_count-12)*8+:8]<=decoded_rx;
                 16,17:payload_length[(rx_count-16)*8+:8]<=decoded_rx;
                 18,19:reserved[(rx_count-18)*8+:8]<=decoded_rx;
                 28,29,30,31:inner_generation[(rx_count-28)*8+:8]<=decoded_rx;
                 32,33,34,35:inner_frame[(rx_count-32)*8+:8]<=decoded_rx;
                 default:begin end
               endcase
             end
           end
         end
       end
     end else if(rx_valid || rx_error || rx_break)begin
       // Caller violating stop-and-wait cannot overwrite accepted packet/cache.
       rx_errors<=rx_errors+1;
     end
   end
 end
 function automatic [31:0] hello_word(input integer index);
   begin case(index)
     0:hello_word=response_status;1:hello_word=32'hF1081C01;2:hello_word=32'hF1080001;
     3:hello_word=32'hF1070001;4:hello_word=50000000;5:hello_word=UART_BAUD;
     6:hello_word=530;7:hello_word=59;8:hello_word=2124;9:hello_word=debug_generation;
     10:hello_word=debug_next_frame;11:hello_word=debug_session;12:hello_word={31'd0,debug_pending};
     13:hello_word=debug_errors;default:hello_word=0;
   endcase end
 endfunction
 function automatic [7:0] response_byte(input integer index);
   reg [31:0] word_value;integer offset;
   begin
     word_value=0;offset=index-20;
     if(index<20)begin
       case(index)
         0:response_byte=8'hF8;1:response_byte=1;2:response_byte=response_command;3:response_byte=response_view;
         4,5,6,7:response_byte=response_session>>((index-4)*8);
         8,9,10,11:response_byte=response_generation>>((index-8)*8);
         12,13,14,15:response_byte=response_frame>>((index-12)*8);
         16,17:response_byte=response_length>>((index-16)*8);
         default:response_byte=0;
       endcase
     end else if(offset<response_length)begin
       if(response_command==8'h81 && response_status==0)word_value=hello_word(offset>>2);
       else if(offset<4)word_value=response_status;
       else if(response_command==8'h83 && response_status==0)word_value=debug_generation;
       else if(sending_snapshot)word_value=snapshot_data;
       response_byte=word_value>>((offset&3)*8);
     end else response_byte=(tx_crc^32'hFFFFFFFF)>>((offset-response_length)*8);
   end
 endfunction
 task automatic fail_command(input [31:0] code);
   begin response_status<=code;response_length<=4;control_errors<=control_errors+1;state<=RESPOND;end
 endtask
 always_ff @(posedge clk)begin
   if(!reset_n)begin
     state<=IDLE;tx_valid<=0;tx_byte<=8'hFF;tx_cursor<=0;tx_crc<=32'hFFFFFFFF;raw_hold<=0;
     debug_generation<=0;debug_next_frame<=0;debug_session<=0;debug_pending<=0;control_errors<=0;
     have_cache<=0;cached_frame<=32'hFFFFFFFF;cached_generation<=0;
     cached_request_words<=0;comparing_retry<=0;
     axi_address<=0;axi_data<=0;aw_done<=0;w_done<=0;word_index<=0;word_count<=0;
     fetched_word<=0;fetch_byte<=0;rx_read_address<=0;operation_guard<=0;reset_wait_count<=0;read_role<=0;
     response_status<=0;response_command<=0;response_view<=0;response_session<=0;
     response_generation<=0;response_frame<=0;response_length<=0;
   end else begin
     if(state!=IDLE && state<RESPOND)operation_guard<=operation_guard+1;
     else operation_guard<=0;
     if(state!=IDLE && state<RESPOND && operation_guard>=1000000)begin
       have_cache<=0;debug_pending<=0;fail_command(E_INNER);
     end else case(state)
       IDLE:if(packet_ready)begin
         response_command<=command|8'h80;response_view<=view;response_session<=session;
         response_generation<=generation;response_frame<=frame;response_status<=0;response_length<=4;
         state<=DISPATCH;
       end
       DISPATCH:begin
         if(packet_error!=0)begin
           response_command<=8'hFF;response_view<=0;response_session<=0;response_generation<=0;response_frame<=0;
           fail_command(packet_error);
         end else if(view>1)fail_command(E_COMMAND);
         else if(command==1)begin
           if(payload_length!=0 || session!=0 || frame!=0)fail_command(E_COMMAND);
           else begin response_generation<=debug_generation;response_length<=56;state<=RESPOND;end
         end else if(command==2)begin
           if(payload_length!=0 || session==0 || frame!=0)fail_command(E_COMMAND);
           else if(generation!=debug_generation)fail_command(E_ID);
           else if(debug_pending && session!=debug_session)fail_command(E_PENDING);
           else begin debug_session<=session;state<=RESPOND;end
         end else if(session==0 || session!=debug_session)fail_command(E_SESSION);
         else if(generation!=debug_generation)fail_command(E_ID);
         else if(command==3)begin
           if(payload_length!=4)fail_command(E_COMMAND);
           else begin word_index<=0;fetch_byte<=0;fetched_word<=0;rx_read_address<=20;state<=FETCH_WAIT;end
         end else if(command==4)begin
           if(payload_length<36 || payload_length>1216 || payload_length[1:0]!=0)fail_command(E_FORMAT);
           else if(inner_generation!=generation || inner_frame!=frame)fail_command(E_ID);
           else if(debug_pending && (!have_cache || frame!=cached_frame))fail_command(E_PENDING);
           else if(frame!=debug_next_frame && !(have_cache && frame==cached_frame))fail_command(E_ID);
           else if(have_cache && frame==cached_frame && (payload_length>>2)!=cached_request_words)
             fail_command(32'h1010F);
           else begin
             comparing_retry<=have_cache && frame==cached_frame;
             if(!(have_cache && frame==cached_frame))have_cache<=0;
             word_index<=0;word_count<=payload_length>>2;fetch_byte<=0;fetched_word<=0;state<=FETCH_SET;
           end
         end else if(command==5)begin
           if(payload_length!=0)fail_command(E_COMMAND);
           else if(!have_cache || !debug_pending || frame!=cached_frame || generation!=cached_generation)fail_command(E_ID);
           else begin response_length<=view==1 ? 240 : 2124;state<=RESPOND;end
         end else if(command==6)begin
           if(payload_length!=0)fail_command(E_COMMAND);
           else if(!have_cache || frame!=cached_frame || generation!=cached_generation)fail_command(E_ID);
           else begin debug_pending<=0;state<=RESPOND;end
         end else if(command==7)begin
           if(payload_length!=0)fail_command(E_COMMAND);
           else if(debug_pending)fail_command(E_PENDING);
           else begin debug_session<=0;state<=RESPOND;end
         end else fail_command(E_COMMAND);
       end
       FETCH_SET:begin rx_read_address<=20+(word_index<<2)+fetch_byte;state<=FETCH_WAIT;end
       FETCH_WAIT:state<=FETCH_GET;
       FETCH_GET:begin
         fetched_word[fetch_byte*8+:8]<=rx_ram_data;
         if(fetch_byte==3)begin
           fetch_byte<=0;state<=WRITE_ADDR;aw_done<=0;w_done<=0;
           axi_address<=command==3 ? 13'h050 : 13'h1000+(word_index<<2);
           axi_data<=command==3 ? 32'd1 : {rx_ram_data,fetched_word[23:0]};
           if(command==3 && {rx_ram_data,fetched_word[23:0]}!=32'hC0DEF00D)fail_command(E_COMMAND);
           if(command==4)begin
             if(comparing_retry)begin
               if({rx_ram_data,fetched_word[23:0]}!=previous_request_word)fail_command(32'h1010F);
               else if(word_index+1==word_count)begin
                 debug_pending<=1;response_length<=view==1 ? 240 : 2124;state<=RESPOND;
               end else begin word_index<=word_index+1;fetched_word<=0;state<=FETCH_SET;end
             end else last_request[word_index]<={rx_ram_data,fetched_word[23:0]};
           end
         end else begin fetch_byte<=fetch_byte+1;state<=FETCH_SET;end
       end
       WRITE_ADDR:begin
         if(axi_awvalid && axi_awready)aw_done<=1;
         if(axi_wvalid && axi_wready)w_done<=1;
         if((aw_done || axi_awready) && (w_done || axi_wready))state<=WRITE_RESP;
       end
       WRITE_RESP:if(axi_bvalid)begin
         if(axi_bresp!=0)begin have_cache<=0;debug_pending<=0;read_role<=3;axi_address<=13'h048;state<=READ_ADDR;end
         else if(command==3)begin reset_wait_count<=0;have_cache<=0;debug_pending<=0;state<=RESET_WAIT;end
         else if(word_index+1==word_count)begin read_role<=0;axi_address<=13'h008;state<=READ_ADDR;end
         else begin word_index<=word_index+1;fetched_word<=0;state<=FETCH_SET;end
       end
       RESET_WAIT:if(reset_wait_count>=520)begin read_role<=2;axi_address<=13'h058;state<=READ_ADDR;end
         else reset_wait_count<=reset_wait_count+1;
       READ_ADDR:if(axi_arready)state<=READ_RESP;
       READ_RESP:if(axi_rvalid)begin
         if(axi_rresp!=0)begin have_cache<=0;debug_pending<=0;fail_command(E_INNER);end
         else case(read_role)
           0:if(axi_rdata[7])begin have_cache<=0;debug_pending<=0;read_role<=3;axi_address<=13'h048;state<=READ_ADDR;end
             else if(axi_rdata[6])begin word_index<=0;read_role<=1;axi_address<=13'h100;state<=READ_ADDR;end
             else begin axi_address<=13'h008;state<=READ_ADDR;end
           1:begin
             snapshots[word_index]<=axi_rdata;
             if(word_index==503)cached_frame<=axi_rdata;
             if(word_index==510)begin cached_generation<=axi_rdata;debug_generation<=axi_rdata;end
             if(word_index==529)begin
               have_cache<=1;debug_pending<=1;debug_next_frame<=cached_frame+1;
               cached_request_words<=word_count;
               response_length<=view==1 ? 240 : 2124;state<=RESPOND;
             end else begin word_index<=word_index+1;axi_address<=axi_address+4;state<=READ_ADDR;end
           end
           2:begin debug_generation<=axi_rdata;debug_next_frame<=0;response_generation<=axi_rdata;
             response_length<=8;state<=RESPOND;end
           3:fail_command(32'h10000|axi_rdata);
         endcase
       end
       RESPOND:begin tx_cursor<=0;tx_crc<=32'hFFFFFFFF;tx_valid<=0;state<=TX_START;end
       TX_START:begin tx_byte<=8'h7E;tx_valid<=1;state<=TX_START_WAIT;end
       TX_START_WAIT:if(tx_valid && tx_ready)begin tx_valid<=0;state<=TX_PREP;end
       TX_PREP:if(tx_cursor==20+response_length+4)state<=TX_END;else state<=TX_RAW;
       TX_RAW:begin
         raw_hold<=response_byte(tx_cursor);
         if(tx_cursor<20+response_length)tx_crc<=crc_byte(tx_crc,response_byte(tx_cursor));
         tx_byte<=(response_byte(tx_cursor)==8'h7E || response_byte(tx_cursor)==8'h7D) ? 8'h7D : response_byte(tx_cursor);
         tx_valid<=1;state<=TX_WAIT;
       end
       TX_WAIT:if(tx_valid && tx_ready)begin
         tx_valid<=0;
         if(raw_hold==8'h7E || raw_hold==8'h7D)state<=TX_ESCAPE;
         else begin tx_cursor<=tx_cursor+1;state<=TX_PREP;end
       end
       TX_ESCAPE:begin tx_byte<=raw_hold^8'h20;tx_valid<=1;state<=TX_ESCAPE_WAIT;end
       TX_ESCAPE_WAIT:if(tx_valid && tx_ready)begin tx_valid<=0;tx_cursor<=tx_cursor+1;state<=TX_PREP;end
       TX_END:begin tx_byte<=8'h7E;tx_valid<=1;state<=TX_END_WAIT;end
       TX_END_WAIT:if(tx_valid && tx_ready)begin tx_valid<=0;state<=IDLE;end
       default:state<=IDLE;
     endcase
   end
 end
endmodule
