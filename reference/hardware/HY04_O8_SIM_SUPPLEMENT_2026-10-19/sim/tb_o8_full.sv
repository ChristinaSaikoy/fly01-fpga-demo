`timescale 1ns/1ps
module tb_o8_full #(parameter integer DEFAULT_SEED=0);
 logic clk=0;always #10 clk=~clk;
 logic reset_n,rx_valid,rx_error,rx_break,tx_valid,tx_ready;
 logic [7:0] rx_byte,tx_byte;
 logic [31:0] debug_generation,debug_next_frame,debug_session,debug_errors;
 logic debug_pending,debug_error;logic [3:0] debug_fsm;
 fly01_o8_byte_endpoint dut(.*);
 `include "sim/o8_protocol_tasks.svh"
 localparam integer N=471,ND=32,TOTAL=300;
 logic [470:0] drive_vec[0:299],noise_vec[0:299],spike_exp[0:299];
 logic signed [17:0] state_exp[0:TOTAL*N-1];
 logic [31:0] acc_exp[0:299],sat_exp[0:299],dn_final_exp[0:95],dn_running[0:31];
 logic [8:0] dn_local[0:31];
 logic [31:0] snapshot[0:529],saved_tail[0:58],word_value;
 integer seed,c,t,gstep,n,d,k,max_cycles,before_count;
 string vector_dir;
 initial begin
  seed=DEFAULT_SEED;if(!$value$plusargs("SEED=%d",seed))seed=DEFAULT_SEED;
  if(seed<0 || seed>5)$fatal(1,"O8_INVALID_SEED");
  vector_dir=$sformatf("sim/vectors/l3_seed%0d",seed);
  $readmemh({vector_dir,"/drive_mask.mem"},drive_vec);
  $readmemh({vector_dir,"/noise_mask.mem"},noise_vec);
  $readmemh({vector_dir,"/spike_mask_expected.mem"},spike_exp);
  $readmemh({vector_dir,"/state_expected.mem"},state_exp);
  $readmemh({vector_dir,"/acc_sat_expected.mem"},acc_exp);
  $readmemh({vector_dir,"/state_sat_expected.mem"},sat_exp);
  $readmemh({vector_dir,"/dn_counts_expected.mem"},dn_final_exp);
  $readmemh("generated/dn_local.mem",dn_local);
  initialize_protocol();max_cycles=0;
  for(c=0;c<3;c=c+1)begin
   science_reset();for(d=0;d<ND;d=d+1)dn_running[d]=0;
   for(t=0;t<100;t=t+1)begin
    gstep=c*100+t;event_count=0;
    for(n=0;n<N;n=n+1)if(drive_vec[gstep][n])begin semantic_events[event_count]=n;event_count=event_count+1;end
    for(n=0;n<N;n=n+1)if(noise_vec[gstep][n])begin semantic_events[event_count]=512+n;event_count=event_count+1;end
    repack(t,t>=25);frame_request(t,0);
    if(streamed!==event_count || debug_next_frame!==t+1 || !debug_pending)$fatal(1,"O8_FRAME_POSTCONDITION");
    for(k=0;k<530;k=k+1)snapshot[k]=response_word(24+k*4);
    if(snapshot[503]!==t || snapshot[510]!==generation_expected || snapshot[511]!==1 ||
     snapshot[512]!==32'hF1070001 || snapshot[513]!==0 || snapshot[514]!==event_count ||
     snapshot[515]!==t || snapshot[516]!==packet_words[7] || snapshot[517]!==generation_expected ||
     snapshot[518]!==packet_size || snapshot[519]!==t+1 || snapshot[520]!==0 || snapshot[521]!==0 ||
     snapshot[522]!==0 || snapshot[523]!==6 || snapshot[524]!==942 || snapshot[525]!==32'h20002 ||
     snapshot[526]!==530 || snapshot[527]!==32'hF107A11D || !snapshot[509][6] || snapshot[509][7])
     $fatal(1,"O8_ACCEPTED_REQUEST_IDENTITY seed=%0d condition=%0d step=%0d",seed,c,t);
    if(snapshot[528]<event_count || snapshot[528]>2*event_count || snapshot[529]<=snapshot[528])$fatal(1,"O8_PROTOCOL_COUNTERS");
    for(n=0;n<N;n=n+1)if($signed(snapshot[n])!==$signed(state_exp[gstep*N+n]))
     $fatal(1,"O8_STATE_MISMATCH seed=%0d condition=%0d step=%0d neuron=%0d got=%0d expected=%0d",seed,c,t,n,$signed(snapshot[n]),$signed(state_exp[gstep*N+n]));
    if(t>=25)for(d=0;d<ND;d=d+1)if(spike_exp[gstep][dn_local[d]])dn_running[d]=dn_running[d]+1;
    for(d=0;d<ND;d=d+1)begin
     if(snapshot[N+d]!==dn_running[d])$fatal(1,"O8_DN_MISMATCH seed=%0d condition=%0d step=%0d dn=%0d",seed,c,t,d);
     if(t==99 && snapshot[N+d]!==dn_final_exp[c*ND+d])$fatal(1,"O8_DN_FINAL_FILE");
    end
    if(snapshot[504]!==acc_exp[gstep] || snapshot[505]!==sat_exp[gstep] || snapshot[506]!==0 || snapshot[507]!==0 ||
     snapshot[508]==0 || snapshot[508]>500000)$fatal(1,"O8_CORE_DIAGNOSTICS seed=%0d condition=%0d step=%0d",seed,c,t);
    if(snapshot[508]>max_cycles)max_cycles=snapshot[508];
    command(5,1,t,59);
    for(d=0;d<59;d=d+1)if(response_word(24+4*d)!==snapshot[471+d])$fatal(1,"O8_FULL_MINIMAL_MISMATCH");
    command(6,0,t,0);if(debug_pending)$fatal(1,"O8_ACK_DID_NOT_RELEASE");
    $display("O8_STEP_PASS seed=%0d condition=%0d timestep=%0d",seed,c,t);
   end
   $display("O8_CASE_PASS seed=%0d condition=%0d steps=100",seed,c);
  end
  if(commits!==300)$fatal(1,"O8_EXACTLY_ONCE_COUNT commits=%0d",commits);
  $display("O8_FULL_PASS seed=%0d steps=300 state=BIT_EXACT dn=EXACT saturation=EXACT overflow=0 drop=0 order=EXACT full_minimal=EXACT commits=%0d max_cycles=%0d",seed,commits,max_cycles);
  $finish;
 end
 initial begin #1000000000;$fatal(1,"O8_FULL_WATCHDOG");end
endmodule
