// Independent simulation byte codec. No host implementation is imported.
logic [7:0] request_bytes[0:4095],response_bytes[0:4095];
logic [31:0] packet_words[0:303],semantic_events[0:941];
integer request_size,response_size,response_count,collect_count;
integer event_count,packet_size,payload_words,streamed,commits,total_core_events;
logic collect_active,collect_escape;
logic [7:0] captured_byte;
logic [31:0] session_id,generation_expected;
integer command_frame;
always @(posedge clk) begin
 if (!reset_n) begin
  collect_active=0;collect_escape=0;collect_count=0;response_size=0;response_count=0;
 end else if(tx_valid && tx_ready) begin
  captured_byte=tx_byte;
  if(captured_byte==8'h7E) begin
   if(collect_active && collect_count>0) begin
    if(collect_escape)$fatal(1,"O8_RESPONSE_DANGLING_ESCAPE");
    response_size=collect_count;response_count=response_count+1;
   end
   collect_active=1;collect_escape=0;collect_count=0;
  end else if(collect_active) begin
   if(captured_byte==8'h7D && !collect_escape) collect_escape=1;
   else begin
    if(collect_count>=4096)$fatal(1,"O8_RESPONSE_OVERFLOW");
    response_bytes[collect_count]=collect_escape?(captured_byte^8'h20):captured_byte;
    collect_count=collect_count+1;collect_escape=0;
   end
  end
 end
end
always @(posedge clk) if(reset_n && dut.u_o7.fsm==10 && dut.u_o7.evt_ready && !dut.u_o7.fault) begin
 if(streamed>=event_count || {22'd0,dut.u_o7.event_read}!==semantic_events[streamed])
  $fatal(1,"O8_ACCEPTED_EVENT_ORDER index=%0d expected=%h actual=%h",streamed,semantic_events[streamed],dut.u_o7.event_read);
 streamed=streamed+1;
 total_core_events=total_core_events+1;
end
always @(posedge clk) if(reset_n && dut.u_o7.step_commit) commits=commits+1;
function automatic [31:0] crc_byte(input [31:0] previous,input [7:0] value);
 reg [31:0] x;integer k;
 begin x=previous^value;for(k=0;k<8;k=k+1)x=(x>>1)^(x[0]?32'hEDB88320:0);crc_byte=x;end
endfunction
function automatic [31:0] crc_word(input [31:0] previous,input [31:0] value);
 reg [31:0] x;integer k;
 begin x=previous;for(k=0;k<4;k=k+1)x=crc_byte(x,value>>(8*k));crc_word=x;end
endfunction
function automatic [31:0] response_word(input integer offset);
 begin response_word={response_bytes[offset+3],response_bytes[offset+2],response_bytes[offset+1],response_bytes[offset]};end
endfunction
task automatic put_word(input integer offset,input logic [31:0] value);
 integer k;begin for(k=0;k<4;k=k+1)request_bytes[offset+k]=value>>(8*k);end
endtask
task automatic make_request(input integer op,input integer view,input logic [31:0] sid,
 input logic [31:0] gen,input integer frame,input integer len);
 integer k;begin
  for(k=0;k<4096;k=k+1)request_bytes[k]=0;
  request_bytes[0]=8'hF8;request_bytes[1]=1;request_bytes[2]=op;request_bytes[3]=view;
  put_word(4,sid);put_word(8,gen);put_word(12,frame);
  request_bytes[16]=len;request_bytes[17]=len>>8;request_size=24+len;
 end
endtask
task automatic seal_request;
 reg [31:0] crc;integer k;begin
  crc=32'hFFFFFFFF;for(k=0;k<request_size-4;k=k+1)crc=crc_byte(crc,request_bytes[k]);
  put_word(request_size-4,crc^32'hFFFFFFFF);
 end
endtask
task automatic send_byte(input logic [7:0] value);
 begin @(negedge clk);rx_byte=value;rx_valid=1;@(negedge clk);rx_valid=0;end
endtask
task automatic send_request;
 integer k;begin
  seal_request();send_byte(8'h7E);
  for(k=0;k<request_size;k=k+1)begin
   if(request_bytes[k]==8'h7E || request_bytes[k]==8'h7D)begin send_byte(8'h7D);send_byte(request_bytes[k]^8'h20);end
   else send_byte(request_bytes[k]);
   repeat(k%3)@(negedge clk);
  end
  send_byte(8'h7E);
 end
endtask
task automatic send_raw_request;
 integer k;begin
  send_byte(8'h7E);
  for(k=0;k<request_size;k=k+1)begin
   if(request_bytes[k]==8'h7E || request_bytes[k]==8'h7D)begin send_byte(8'h7D);send_byte(request_bytes[k]^8'h20);end
   else send_byte(request_bytes[k]);
  end
  send_byte(8'h7E);
 end
endtask
task automatic wait_response(input integer before_count);
 integer guard,k,len;reg [31:0] crc;
 begin
  guard=0;while(response_count==before_count)begin @(negedge clk);guard=guard+1;
   if(guard>700000)$fatal(1,"O8_RESPONSE_TIMEOUT before=%0d fsm=%0d",before_count,debug_fsm);end
  if(response_count!=before_count+1)$fatal(1,"O8_UNEXPECTED_EXTRA_RESPONSE");
  if(response_size<28 || response_bytes[0]!==8'hF8 || response_bytes[1]!==1)$fatal(1,"O8_RESPONSE_HEADER");
  len={response_bytes[17],response_bytes[16]};
  if(response_size!==len+24 || response_bytes[18]!==0 || response_bytes[19]!==0)$fatal(1,"O8_RESPONSE_LENGTH");
  crc=32'hFFFFFFFF;for(k=0;k<response_size-4;k=k+1)crc=crc_byte(crc,response_bytes[k]);
  if(response_word(response_size-4)!==(crc^32'hFFFFFFFF))$fatal(1,"O8_RESPONSE_CRC");
 end
endtask
task automatic check_response(input integer op,input integer view,input logic [31:0] sid,
 input logic [31:0] gen,input integer frame,input integer words);
 begin
  if(response_bytes[2]!==8'(op|8'h80) || response_bytes[3]!==8'(view) || response_word(4)!==sid ||
   response_word(8)!==gen || response_word(12)!==32'(frame) || response_word(20)!==0)
   $fatal(1,"O8_RESPONSE_IDENTITY op=%0d gotop=%0h sid=%h gen=%h frame=%h status=%h",op,response_bytes[2],response_word(4),response_word(8),response_word(12),response_word(20));
  if(response_size!==28+words*4)$fatal(1,"O8_RESPONSE_WORDS expected=%0d gotbytes=%0d",words,response_size);
 end
endtask
task automatic command(input integer op,input integer view,input integer frame,input integer words);
 integer before_count;begin
  before_count=response_count;make_request(op,view,session_id,generation_expected,frame,0);
  send_request();wait_response(before_count);check_response(op,view,session_id,generation_expected,frame,words);
 end
endtask
task automatic initialize_protocol;
 integer before_count;begin
  session_id=32'h197D7E31;generation_expected=0;streamed=0;event_count=0;commits=0;total_core_events=0;
  reset_n=0;rx_byte=0;rx_valid=0;rx_error=0;rx_break=0;tx_ready=1;
  repeat(8)@(negedge clk);reset_n=1;repeat(8)@(negedge clk);
  before_count=response_count;make_request(1,0,0,0,0,0);send_request();wait_response(before_count);
  check_response(1,0,0,0,0,13);
  if(response_word(24)!==32'hF1081C01 || response_word(28)!==32'hF1080001 || response_word(32)!==32'hF1070001 ||
   response_word(36)!==50000000 || response_word(44)!==530 || response_word(48)!==59 || response_word(52)!==2124)
   $fatal(1,"O8_HELLO_CAPABILITIES");
  command(2,0,0,0);
 end
endtask
task automatic science_reset;
 integer before_count;begin
  before_count=response_count;make_request(3,0,session_id,generation_expected,0,4);put_word(20,32'hC0DEF00D);
  send_request();wait_response(before_count);generation_expected=generation_expected+1;
  check_response(3,0,session_id,generation_expected,0,1);
  if(response_word(24)!==generation_expected || debug_pending || debug_next_frame!==0)$fatal(1,"O8_RESET_POSTCONDITION");
 end
endtask
task automatic repack(input integer frame,input integer dn_enabled);
 integer k,offset;reg [31:0] crc;begin
  payload_words=(10*event_count+31)/32;packet_size=9+payload_words;
  for(k=0;k<304;k=k+1)packet_words[k]=0;
  for(k=0;k<event_count;k=k+1)begin
   offset=(10*k)%32;packet_words[8+(10*k)/32]|=semantic_events[k]<<offset;
   if(offset>22)packet_words[9+(10*k)/32]|=semantic_events[k]>>(32-offset);
  end
  packet_words[0]=32'hF107C001;packet_words[1]=32'hF1070001;packet_words[2]=generation_expected;
  packet_words[3]=frame;packet_words[4]=event_count;packet_words[5]=32'h10000|dn_enabled;packet_words[6]=frame;
  crc=32'hFFFFFFFF;for(k=0;k<7;k=k+1)crc=crc_word(crc,packet_words[k]);
  for(k=0;k<payload_words;k=k+1)crc=crc_word(crc,packet_words[8+k]);
  packet_words[7]=crc^32'hFFFFFFFF;packet_words[8+payload_words]=32'hF107C0DE;
 end
endtask
task automatic make_frame_request(input integer frame,input integer view);
 integer k;begin
  make_request(4,view,session_id,generation_expected,frame,packet_size*4);
  for(k=0;k<packet_size;k=k+1)put_word(20+k*4,packet_words[k]);
 end
endtask
task automatic frame_request(input integer frame,input integer view);
 integer before_count;begin
  before_count=response_count;streamed=0;make_frame_request(frame,view);send_request();wait_response(before_count);
  check_response(4,view,session_id,generation_expected,frame,view?59:530);
 end
endtask
