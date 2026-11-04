`timescale 1ns/1ps
module fly01_integration_top #(parameter integer CLOCK_HZ=50000000,
 parameter integer UART_DIV=434,parameter integer PWM_LIMIT=800,parameter integer BENCH_MS=750,
 parameter integer I2C_MOTION_ENABLE=0,parameter integer BENCH_PWM=1800)(
 input wire sys_clk,sys_rst_n,input wire vision_rx,output wire vision_tx,
 input wire uart_rxd,output wire uart_txd,inout wire motor_scl,motor_sda,
 output wire [3:0] led);
 localparam integer AGE_CYCLES=(CLOCK_HZ/1000)*250;
 (* ASYNC_REG="TRUE" *) reg reset_meta,reset_sync;
 always @(posedge sys_clk)begin reset_meta<=sys_rst_n;reset_sync<=reset_meta;end
 wire reset_n=reset_sync;
 wire [7:0] rx_data,pc_data;wire rx_valid,pc_valid,rx_error,pc_error;
 fly01_uart_rx #(.CLKS_PER_BIT(UART_DIV)) camera_rx(.clk(sys_clk),.reset_n(reset_n),.rx(vision_rx),.data(rx_data),.valid(rx_valid),.framing_error(rx_error));
 fly01_uart_rx #(.CLKS_PER_BIT(UART_DIV)) pc_rx(.clk(sys_clk),.reset_n(reset_n),.rx(uart_rxd),.data(pc_data),.valid(pc_valid),.framing_error(pc_error));
 wire packet_valid;wire [7:0] kind;wire [31:0] session,seq,bad_count;wire [6:0] length;wire [511:0] payload;
 fly01_packet_rx #(.TIMEOUT_CYCLES((CLOCK_HZ/1000)*20)) packets(.clk(sys_clk),.reset_n(reset_n),.byte_valid(rx_valid),.byte_data(rx_data),.valid(packet_valid),.kind(kind),.session(session),.seq(seq),.length(length),.payload(payload),.bad_count(bad_count));
 reg [31:0] active_session,last_seq,age,request_timer;reg seen,usable,armed,core_reset;
 reg observation_valid,observation_usable;
 reg [470:0] observation_mask;reg observation_mask_valid,motion_activity;
 reg [470:0] incoming_mask;
 always @*begin
 incoming_mask=0;
 incoming_mask[44]=payload[32];
 incoming_mask[51]=payload[33];
 incoming_mask[60]=payload[34];
 incoming_mask[61]=payload[35];
 incoming_mask[65]=payload[36];
 incoming_mask[69]=payload[37];
 incoming_mask[71]=payload[38];
 incoming_mask[72]=payload[39];
 incoming_mask[75]=payload[40];
 incoming_mask[77]=payload[41];
 incoming_mask[80]=payload[42];
 incoming_mask[81]=payload[43];
 incoming_mask[82]=payload[44];
 incoming_mask[90]=payload[45];
 incoming_mask[93]=payload[46];
 incoming_mask[94]=payload[47];
 incoming_mask[100]=payload[48];
 incoming_mask[102]=payload[49];
 incoming_mask[104]=payload[50];
 incoming_mask[106]=payload[51];
 incoming_mask[107]=payload[52];
 incoming_mask[111]=payload[53];
 incoming_mask[112]=payload[54];
 incoming_mask[114]=payload[55];
 incoming_mask[115]=payload[56];
 incoming_mask[117]=payload[57];
 incoming_mask[118]=payload[58];
 incoming_mask[119]=payload[59];
 incoming_mask[120]=payload[60];
 incoming_mask[122]=payload[61];
 incoming_mask[123]=payload[62];
 incoming_mask[124]=payload[63];
 incoming_mask[125]=payload[64];
 incoming_mask[126]=payload[65];
 incoming_mask[127]=payload[66];
 incoming_mask[128]=payload[67];
 incoming_mask[130]=payload[68];
 incoming_mask[132]=payload[69];
 incoming_mask[133]=payload[70];
 incoming_mask[134]=payload[71];
 incoming_mask[135]=payload[72];
 incoming_mask[137]=payload[73];
 incoming_mask[138]=payload[74];
 incoming_mask[139]=payload[75];
 incoming_mask[141]=payload[76];
 incoming_mask[142]=payload[77];
 incoming_mask[144]=payload[78];
 incoming_mask[145]=payload[79];
 incoming_mask[146]=payload[80];
 incoming_mask[147]=payload[81];
 incoming_mask[149]=payload[82];
 incoming_mask[150]=payload[83];
 incoming_mask[151]=payload[84];
 incoming_mask[153]=payload[85];
 incoming_mask[155]=payload[86];
 incoming_mask[156]=payload[87];
 incoming_mask[157]=payload[88];
 incoming_mask[158]=payload[89];
 incoming_mask[159]=payload[90];
 incoming_mask[160]=payload[91];
 incoming_mask[161]=payload[92];
 incoming_mask[162]=payload[93];
 incoming_mask[163]=payload[94];
 incoming_mask[164]=payload[95];
 incoming_mask[165]=payload[96];
 incoming_mask[168]=payload[97];
 incoming_mask[169]=payload[98];
 incoming_mask[170]=payload[99];
 incoming_mask[171]=payload[100];
 incoming_mask[172]=payload[101];
 incoming_mask[173]=payload[102];
 incoming_mask[174]=payload[103];
 incoming_mask[175]=payload[104];
 incoming_mask[176]=payload[105];
 incoming_mask[177]=payload[106];
 incoming_mask[178]=payload[107];
 incoming_mask[179]=payload[108];
 incoming_mask[181]=payload[109];
 incoming_mask[182]=payload[110];
 incoming_mask[183]=payload[111];
 incoming_mask[184]=payload[112];
 incoming_mask[185]=payload[113];
 incoming_mask[186]=payload[114];
 incoming_mask[187]=payload[115];
 incoming_mask[188]=payload[116];
 incoming_mask[189]=payload[117];
 incoming_mask[190]=payload[118];
 incoming_mask[191]=payload[119];
 incoming_mask[192]=payload[120];
 incoming_mask[193]=payload[121];
 incoming_mask[194]=payload[122];
 incoming_mask[195]=payload[123];
 incoming_mask[196]=payload[124];
 incoming_mask[197]=payload[125];
 incoming_mask[198]=payload[126];
 incoming_mask[199]=payload[127];
 incoming_mask[200]=payload[128];
 incoming_mask[201]=payload[129];
 incoming_mask[202]=payload[130];
 incoming_mask[203]=payload[131];
 incoming_mask[204]=payload[132];
 incoming_mask[205]=payload[133];
 incoming_mask[207]=payload[134];
 incoming_mask[210]=payload[135];
 incoming_mask[212]=payload[136];
 incoming_mask[213]=payload[137];
 incoming_mask[214]=payload[138];
 incoming_mask[215]=payload[139];
 incoming_mask[216]=payload[140];
 incoming_mask[217]=payload[141];
 incoming_mask[218]=payload[142];
 incoming_mask[219]=payload[143];
 incoming_mask[220]=payload[144];
 incoming_mask[222]=payload[145];
 incoming_mask[223]=payload[146];
 incoming_mask[224]=payload[147];
 incoming_mask[226]=payload[148];
 incoming_mask[227]=payload[149];
 incoming_mask[229]=payload[150];
 incoming_mask[230]=payload[151];
 incoming_mask[231]=payload[152];
 incoming_mask[232]=payload[153];
 incoming_mask[233]=payload[154];
 incoming_mask[234]=payload[155];
 incoming_mask[235]=payload[156];
 incoming_mask[236]=payload[157];
 incoming_mask[237]=payload[158];
 incoming_mask[238]=payload[159];
 incoming_mask[239]=payload[160];
 incoming_mask[240]=payload[161];
 incoming_mask[242]=payload[162];
 incoming_mask[243]=payload[163];
 incoming_mask[244]=payload[164];
 incoming_mask[245]=payload[165];
 incoming_mask[246]=payload[166];
 incoming_mask[247]=payload[167];
 incoming_mask[248]=payload[168];
 incoming_mask[249]=payload[169];
 incoming_mask[250]=payload[170];
 incoming_mask[251]=payload[171];
 incoming_mask[252]=payload[172];
 incoming_mask[253]=payload[173];
 incoming_mask[254]=payload[174];
 incoming_mask[255]=payload[175];
 incoming_mask[256]=payload[176];
 incoming_mask[257]=payload[177];
 incoming_mask[258]=payload[178];
 incoming_mask[259]=payload[179];
 incoming_mask[260]=payload[180];
 incoming_mask[261]=payload[181];
 incoming_mask[262]=payload[182];
 incoming_mask[263]=payload[183];
 incoming_mask[264]=payload[184];
 incoming_mask[265]=payload[185];
 incoming_mask[266]=payload[186];
 incoming_mask[267]=payload[187];
 incoming_mask[269]=payload[188];
 incoming_mask[270]=payload[189];
 incoming_mask[271]=payload[190];
 incoming_mask[272]=payload[191];
 incoming_mask[273]=payload[192];
 incoming_mask[274]=payload[193];
 incoming_mask[275]=payload[194];
 incoming_mask[276]=payload[195];
 incoming_mask[277]=payload[196];
 incoming_mask[278]=payload[197];
 incoming_mask[279]=payload[198];
 incoming_mask[280]=payload[199];
 incoming_mask[281]=payload[200];
 incoming_mask[282]=payload[201];
 incoming_mask[283]=payload[202];
 incoming_mask[284]=payload[203];
 incoming_mask[286]=payload[204];
 incoming_mask[287]=payload[205];
 incoming_mask[288]=payload[206];
 incoming_mask[289]=payload[207];
 incoming_mask[291]=payload[208];
 incoming_mask[292]=payload[209];
 incoming_mask[293]=payload[210];
 incoming_mask[294]=payload[211];
 incoming_mask[295]=payload[212];
 incoming_mask[296]=payload[213];
 incoming_mask[297]=payload[214];
 incoming_mask[298]=payload[215];
 incoming_mask[299]=payload[216];
 incoming_mask[300]=payload[217];
 incoming_mask[301]=payload[218];
 incoming_mask[302]=payload[219];
 incoming_mask[303]=payload[220];
 incoming_mask[304]=payload[221];
 incoming_mask[305]=payload[222];
 incoming_mask[306]=payload[223];
 incoming_mask[307]=payload[224];
 incoming_mask[308]=payload[225];
 incoming_mask[309]=payload[226];
 incoming_mask[310]=payload[227];
 incoming_mask[311]=payload[228];
 incoming_mask[312]=payload[229];
 incoming_mask[313]=payload[230];
 incoming_mask[314]=payload[231];
 incoming_mask[315]=payload[232];
 incoming_mask[316]=payload[233];
 incoming_mask[317]=payload[234];
 incoming_mask[319]=payload[235];
 incoming_mask[320]=payload[236];
 incoming_mask[321]=payload[237];
 incoming_mask[322]=payload[238];
 incoming_mask[323]=payload[239];
 incoming_mask[325]=payload[240];
 incoming_mask[326]=payload[241];
 incoming_mask[327]=payload[242];
 incoming_mask[328]=payload[243];
 incoming_mask[330]=payload[244];
 incoming_mask[331]=payload[245];
 incoming_mask[332]=payload[246];
 incoming_mask[333]=payload[247];
 incoming_mask[334]=payload[248];
 incoming_mask[335]=payload[249];
 incoming_mask[336]=payload[250];
 incoming_mask[337]=payload[251];
 incoming_mask[338]=payload[252];
 incoming_mask[339]=payload[253];
 incoming_mask[340]=payload[254];
 incoming_mask[341]=payload[255];
 incoming_mask[342]=payload[256];
 incoming_mask[343]=payload[257];
 incoming_mask[344]=payload[258];
 incoming_mask[345]=payload[259];
 incoming_mask[346]=payload[260];
 incoming_mask[347]=payload[261];
 incoming_mask[348]=payload[262];
 incoming_mask[349]=payload[263];
 incoming_mask[350]=payload[264];
 incoming_mask[351]=payload[265];
 incoming_mask[352]=payload[266];
 incoming_mask[353]=payload[267];
 incoming_mask[354]=payload[268];
 incoming_mask[355]=payload[269];
 incoming_mask[356]=payload[270];
 incoming_mask[357]=payload[271];
 incoming_mask[358]=payload[272];
 incoming_mask[359]=payload[273];
 incoming_mask[360]=payload[274];
 incoming_mask[362]=payload[275];
 incoming_mask[363]=payload[276];
 incoming_mask[364]=payload[277];
 incoming_mask[365]=payload[278];
 incoming_mask[366]=payload[279];
 incoming_mask[367]=payload[280];
 incoming_mask[368]=payload[281];
 incoming_mask[369]=payload[282];
 incoming_mask[370]=payload[283];
 incoming_mask[371]=payload[284];
 incoming_mask[372]=payload[285];
 incoming_mask[373]=payload[286];
 incoming_mask[374]=payload[287];
 incoming_mask[375]=payload[288];
 incoming_mask[376]=payload[289];
 incoming_mask[377]=payload[290];
 incoming_mask[378]=payload[291];
 incoming_mask[379]=payload[292];
 incoming_mask[380]=payload[293];
 incoming_mask[382]=payload[294];
 incoming_mask[388]=payload[295];
 incoming_mask[389]=payload[296];
 incoming_mask[392]=payload[297];
 incoming_mask[393]=payload[298];
 incoming_mask[394]=payload[299];
 incoming_mask[395]=payload[300];
 incoming_mask[396]=payload[301];
 incoming_mask[397]=payload[302];
 incoming_mask[398]=payload[303];
 incoming_mask[399]=payload[304];
 incoming_mask[400]=payload[305];
 incoming_mask[402]=payload[306];
 incoming_mask[404]=payload[307];
 incoming_mask[405]=payload[308];
 incoming_mask[410]=payload[309];
 incoming_mask[411]=payload[310];
 incoming_mask[412]=payload[311];
 incoming_mask[413]=payload[312];
 incoming_mask[414]=payload[313];
 incoming_mask[415]=payload[314];
 incoming_mask[416]=payload[315];
 incoming_mask[417]=payload[316];
 incoming_mask[418]=payload[317];
 incoming_mask[420]=payload[318];
 incoming_mask[421]=payload[319];
 incoming_mask[422]=payload[320];
 incoming_mask[423]=payload[321];
 incoming_mask[424]=payload[322];
 incoming_mask[425]=payload[323];
 incoming_mask[426]=payload[324];
 incoming_mask[427]=payload[325];
 incoming_mask[430]=payload[326];
 incoming_mask[432]=payload[327];
 incoming_mask[434]=payload[328];
 incoming_mask[435]=payload[329];
 incoming_mask[436]=payload[330];
 incoming_mask[441]=payload[331];
 incoming_mask[442]=payload[332];
 incoming_mask[443]=payload[333];
 incoming_mask[445]=payload[334];
 incoming_mask[446]=payload[335];
 incoming_mask[452]=payload[336];
 incoming_mask[454]=payload[337];
 incoming_mask[460]=payload[338];
 incoming_mask[462]=payload[339];
 incoming_mask[463]=payload[340];
 incoming_mask[465]=payload[341];
 incoming_mask[466]=payload[342];
 end
wire observation_ready;
 reg [1:0] observation_group;reg [15:0] observation_age_ms;
 reg [31:0] observation_session,observation_source_seq;
 wire [31:0] model_step;
 wire [31:0] observation_target_step=model_step+1;
 reg [31:0] observation_queue_cycles;
 reg noise_valid;wire noise_ready;reg [470:0] noise_mask;reg [31:0] noise_step,noise_session;
 reg initialized,noise_consumed;reg [31:0] consumed_step;
 wire [31:0] deadline_miss_count,completed_step_count,output_step,adopted_session,adopted_seq;
 wire output_valid,adopted_usable,fault;wire [7:0] fault_code;wire [1023:0] dn;
 wire [31:0] adopted_age_cycles;reg [31:0] enable_min_step;
 wire evt_valid,evt_ready,evt_noise,commit,busy,done,dn_enable;
 wire [8:0] evt_neuron;wire [4:0] dn_sel;wire [31:0] dn_data,cycles,acc_sat,state_sat,overflow,drop;
 wire signed [17:0] probe_data;
 wire neural_reset_n=reset_n&&!core_reset;
 fly01_autonomous_scheduler #(.CLOCK_HZ(CLOCK_HZ),.USE_VISUAL_MASK(1)) scheduler(.clk(sys_clk),.reset_n(neural_reset_n),
 .run_enable(seen),.debug_mode(1'b0),.observation_valid(observation_valid),.observation_ready(observation_ready),
 .observation_usable(observation_usable),.observation_integrity_ok(1'b1),.observation_session(observation_session),
 .observation_source_seq(observation_source_seq),.observation_age_ms(observation_age_ms),.observation_queue_cycles(observation_queue_cycles),.observation_group(observation_group),
 .observation_target_step(observation_target_step),.observation_mask(observation_mask),.observation_mask_valid(observation_mask_valid),.noise_valid(noise_valid),.noise_ready(noise_ready),
 .noise_step(noise_step),.noise_session(noise_session),.noise_integrity_ok(1'b1),.noise_mask(noise_mask),
 .core_evt_valid(evt_valid),.core_evt_ready(evt_ready),.core_evt_kind_noise(evt_noise),.core_evt_neuron(evt_neuron),
 .core_step_commit(commit),.core_step_busy(busy),.core_step_done(done),.core_dn_count_enable(dn_enable),
 .core_dn_counter_sel(dn_sel),.core_dn_counter_data(dn_data),.model_step(model_step),.deadline_miss_count(deadline_miss_count),
 .completed_step_count(completed_step_count),.output_valid(output_valid),.output_ready(1'b1),.output_step(output_step),
 .output_dn_delta(dn),.adopted_session(adopted_session),.adopted_seq(adopted_seq),.adopted_usable(adopted_usable),.adopted_age_cycles(adopted_age_cycles),.fault(fault),.fault_code(fault_code));
 fly01_formal_top neural(.sys_clk(sys_clk),.sys_rst_n(neural_reset_n),.evt_valid(evt_valid),.evt_ready(evt_ready),
 .evt_kind_noise(evt_noise),.evt_neuron(evt_neuron),.step_commit(commit),.dn_count_enable(dn_enable),.step_busy(busy),.step_done(done),
 .state_probe_addr(9'b0),.state_probe_data(probe_data),.dn_counter_sel(dn_sel),.dn_counter_data(dn_data),.timestep_cycles(cycles),
 .acc_saturation_count(acc_sat),.state_saturation_count(state_sat),.overflow_count(overflow),.drop_count(drop));
 wire post_valid;wire signed [31:0] yaw;
 fly01_postprocess post(.clk(sys_clk),.reset_n(neural_reset_n),.valid(output_valid),.dn(dn),.valid_out(post_valid),.yaw_q20(yaw));
 wire v2=kind==7&&length==43;
 wire new_obs=packet_valid&&((kind==1&&length==4)||v2)&&session!=0;
 wire invalid_obs=new_obs&&(!payload[0]||payload[15:8]>3||payload[31:16]>=250||(v2&&(payload[343]||payload[7:2]!=0||payload[15:8]!=0)));
 wire session_change=new_obs&&session!=active_session;
 reg bench_active,bench_start,bench_stop;
 reg [9:0] right_trim;
 reg [10:0] right_limit;
 reg trim_receiving;
 reg [3:0] trim_index;
 reg [15:0] trim_value,limit_value;
 reg [31:0] trim_age;
 wire pc_stop=pc_valid&&pc_data=="S";
 wire pc_retry=pc_valid&&pc_data=="R"&&!trim_receiving;
 wire external_stop=pc_stop||pc_retry||(packet_valid&&kind==4&&session==active_session);
 wire disarm_now=external_stop||invalid_obs||session_change||!seen||!usable||age>=AGE_CYCLES||fault||overflow!=0||drop!=0;
 wire unsafe_now=!motion_activity||disarm_now;
 reg [31:0] result_age;reg result_eligible;
 wire i2c_scl_low,i2c_sda_low,i2c_fault,i2c_busy,i2c_zero_ack;
 wire [2:0] i2c_fault_code;
 wire [3:0] i2c_ack_count;
 wire [31:0] i2c_frames;
 wire signed [15:0] i2c_acked_left,i2c_acked_right;
 wire [3:0] i2c_first_fault_acks;
 // An explicit R only restarts the actuator transport, never the neural core.
 reg i2c_retry_pending,i2c_retry_reset,retry_epoch;
 always @(posedge sys_clk)begin
  if(!reset_n)begin i2c_retry_pending<=0;i2c_retry_reset<=0;retry_epoch<=0;end
  else begin
   i2c_retry_reset<=0;
   if(i2c_retry_reset)retry_epoch<=~retry_epoch;
   if(pc_retry&&!armed&&!bench_active&&i2c_fault)i2c_retry_pending<=1;
   if(i2c_retry_pending&&!i2c_busy)begin
    i2c_retry_pending<=0;i2c_retry_reset<=1;
   end
  end
 end
 // Tdddd,dddd LF: decimal trim and cap, atomically committed while disarmed.
 // S always interrupts a partial frame. Framing errors and 20 ms gaps abort it.
 always @(posedge sys_clk)begin
  if(!reset_n)begin
   right_trim<=10'd400;right_limit<=11'd1800;trim_receiving<=0;
   trim_index<=0;trim_value<=0;limit_value<=0;trim_age<=0;
  end else begin
   if(trim_receiving)trim_age<=trim_age+1;
   if(pc_stop||pc_error||trim_age>=(CLOCK_HZ/1000)*20)begin
    trim_receiving<=0;trim_age<=0;
   end else if(pc_valid)begin
    trim_age<=0;
    if(pc_data=="T"&&!armed&&!bench_active)begin
     trim_receiving<=1;trim_index<=0;trim_value<=0;limit_value<=0;
    end else if(trim_receiving)begin
     if(trim_index<4 && pc_data>="0" && pc_data<="9")begin
      trim_value<=trim_value*10+(pc_data-8'd48);trim_index<=trim_index+1;
     end else if(trim_index==4 && pc_data==",")trim_index<=5;
     else if(trim_index>=5 && trim_index<9 && pc_data>="0" && pc_data<="9")begin
      limit_value<=limit_value*10+(pc_data-8'd48);trim_index<=trim_index+1;
     end else if(trim_index==9 && pc_data==8'd10)begin
      trim_receiving<=0;
      if(!armed&&!bench_active&&trim_value<=800&&limit_value>=1200&&limit_value<=2000)begin
       right_trim<=trim_value[9:0];right_limit<=limit_value[10:0];
      end
     end else trim_receiving<=0;
    end
   end
  end
 end
 wire motor_reset_n=reset_n&&!i2c_retry_reset;
 wire stop_motion=unsafe_now||result_age>=AGE_CYCLES||i2c_fault||i2c_retry_pending||i2c_retry_reset;
 // Explicit B command is an independent raised-wheel diagnostic, not neural control.
 localparam integer BENCH_CYCLES=(CLOCK_HZ/1000)*BENCH_MS;
 reg [31:0] bench_left;
 reg signed [15:0] bench_setting,bench_pwm;
 initial if(BENCH_PWM!=1200&&BENCH_PWM!=1600&&BENCH_PWM!=1800&&BENCH_PWM!=2000)
  $error("Bench PWM must be one of the four approved diagnostic levels");
 wire bench_request=pc_valid&&pc_data=="B"&&!trim_receiving;
 initial if(BENCH_MS<=0||BENCH_MS>750)$error("Diagnostic pulse must be 1..750 ms");
 always @(posedge sys_clk)begin
   if(!reset_n)begin bench_active<=0;bench_start<=0;bench_stop<=0;bench_left<=0;bench_setting<=BENCH_PWM;bench_pwm<=BENCH_PWM;end
   else begin
     bench_start<=0;bench_stop<=0;
     // Selectors change only the next pulse; they never start motion.
     if(!bench_active && pc_valid&&!trim_receiving)begin
      case(pc_data)
       "1":bench_setting<=16'sd1200;
       "2":bench_setting<=16'sd1600;
       "3":bench_setting<=16'sd1800;
       "4":bench_setting<=16'sd2000;
       default:begin end
      endcase
     end
     if(external_stop||fault)begin
       if(bench_active)bench_stop<=1;
       bench_active<=0;bench_left<=0;
     end else if(bench_request&&!bench_active)begin
       bench_active<=1;bench_start<=1;bench_left<=BENCH_CYCLES;bench_pwm<=bench_setting;
     end else if(bench_active)begin
       if(bench_left<=1)begin bench_active<=0;bench_stop<=1;bench_left<=0;end
       else bench_left<=bench_left-1;
     end
   end
 end
 wire signed [15:0] pwm;wire pwm_valid;
 fly01_spin_pwm #(.LIMIT(PWM_LIMIT),.PRESERVE_NONZERO(1)) actuator_scale(.clk(sys_clk),.reset_n(neural_reset_n),.valid(post_valid),.yaw_q20(yaw),.valid_out(pwm_valid),.pwm(pwm));
 // R6 actuator calibration only: frozen yaw and raw PWM remain unchanged.
 // Sparse above-deadband neural commands receive 1200 start duty, capped at 1600.
 // A 600 ms envelope bridges sparse spikes; every existing safety gate cancels it.
 wire neural_command_ok=armed&&result_eligible&&output_step>=enable_min_step&&!stop_motion&&!bench_active;
 wire signed [15:0] motor_pwm;wire motor_pwm_valid;
 fly01_motor_envelope #(.HOLD_CYCLES((CLOCK_HZ/1000)*600)) motor_envelope(
   .clk(sys_clk),.reset_n(reset_n),.permit(neural_command_ok),
   .valid(pwm_valid),.raw_pwm(pwm),.valid_out(motor_pwm_valid),.pwm(motor_pwm));
 // Runtime right-channel magnitude trim; default +400, zero remains zero.
 // Forward-only operator calibration is reused as an unverified reverse candidate.
 // Cap at the previously exercised raw range; zero and every safety gate stay zero.
 wire signed [16:0] right_extended={motor_pwm[15],motor_pwm};
 wire [16:0] right_magnitude=motor_pwm[15]?-right_extended:right_extended;
 wire [17:0] right_boosted={1'b0,right_magnitude}+{8'b0,right_trim};
 wire signed [15:0] right_bounded=right_boosted>{7'b0,right_limit}?$signed({5'b0,right_limit}):$signed(right_boosted[15:0]);
 wire signed [15:0] right_neural_pwm=motor_pwm==0?16'sd0:
      (motor_pwm[15]?-right_bounded:right_bounded);
 // WORK18: electrical open-drain ONLY at top-level; external 3.3V pull-ups mandatory.
 assign motor_scl=i2c_scl_low ? 1'b0 : 1'bz;
 assign motor_sda=i2c_sda_low ? 1'b0 : 1'bz;
 fly01_motor_i2c #(.CLK_HZ(CLOCK_HZ),.BUS_HZ(50000),
    .ENABLE_MOTION(I2C_MOTION_ENABLE)) motor_i2c(
   .clk(sys_clk),.reset_n(motor_reset_n),
   .stop(external_stop||bench_stop||(!bench_active&&stop_motion)),
   .command_valid(bench_active?bench_start:
     (motor_pwm_valid&&neural_command_ok)),
   .left_pwm(bench_active?-bench_pwm:-motor_pwm),
   .right_pwm(bench_active?bench_pwm:right_neural_pwm),
   .scl_in(motor_scl),.sda_in(motor_sda),
   .scl_drive_low(i2c_scl_low),.sda_drive_low(i2c_sda_low),
   .fault(i2c_fault),.fault_code(i2c_fault_code),
   .zero_acknowledged(i2c_zero_ack),.completed_frames(i2c_frames),
   .last_acks(i2c_ack_count),.i2c_busy(i2c_busy),
   .last_acked_left(i2c_acked_left),.last_acked_right(i2c_acked_right),.first_fault_acks(i2c_first_fault_acks));
 wire packet_tx_ready,tx_valid,tx_ready;wire [7:0] tx_data;
 reg request_valid;
 fly01_packet_tx requests(.clk(sys_clk),.reset_n(reset_n),.valid(request_valid),.ready(packet_tx_ready),.kind(8'd3),
 .session(active_session),.seq(model_step),.length(7'd0),.payload(512'b0),.byte_valid(tx_valid),.byte_ready(tx_ready),.byte_data(tx_data));
 fly01_uart_tx #(.CLKS_PER_BIT(UART_DIV)) camera_tx(.clk(sys_clk),.reset_n(reset_n),.valid(tx_valid),.ready(tx_ready),.data(tx_data),.tx(vision_tx));
 reg [31:0] observation_overwrites,diagnostic_drops,previous_flags;
 wire [31:0] flags={17'b0,bench_active,fault_code, result_eligible,fault,stop_motion,armed,usable,seen};
 // I2C mode replaces the unused ASCII preview with a versioned status extension.
 // i2c_frames counts completed transactions, including faults, not wheel motion.
 // Little-endian extension at diagnostic payload[44:64]:
 // I2C5, ACK/status/fault/drives, selected/latched PWM, last ACKed L/R, first-fault ACKs.
 // This is transaction evidence, never proof of motor execution.
 wire [159:0] motor_last_frame={{2'b01,retry_epoch,right_limit,right_trim},{4'b0,i2c_first_fault_acks},i2c_acked_right,i2c_acked_left,bench_pwm,bench_setting,{6'b0,i2c_sda_low,i2c_scl_low},
   {5'b0,i2c_fault_code},{4'b0,(I2C_MOTION_ENABLE!=0),i2c_busy,i2c_zero_ack,i2c_fault},
   {4'b0,i2c_ack_count},32'h35433249};
 wire [31:0] motor_frame_count=i2c_frames;
 reg [31:0] diagnostic_timer;
 wire diagnostic_heartbeat=diagnostic_timer>=(CLOCK_HZ/10)-1;
 always @(posedge sys_clk)begin
   if(!reset_n||diagnostic_heartbeat)diagnostic_timer<=0;
   else diagnostic_timer<=diagnostic_timer+1;
 end
 wire diagnostic_ready,diagnostic_byte_valid,diagnostic_byte_ready;wire [7:0] diagnostic_byte;
 wire [31:0] dn_mask;
 genvar d;generate for(d=0;d<32;d=d+1)begin:diag_dn assign dn_mask[d]=dn[d*32];end endgenerate
 wire [511:0] diagnostic_payload={motor_last_frame,motor_frame_count,diagnostic_drops,observation_overwrites,bad_count,deadline_miss_count,
    flags,adopted_age_cycles,result_age,yaw,dn_mask,adopted_seq};
 wire diagnostic_event=post_valid || flags!=previous_flags || diagnostic_heartbeat;
 fly01_packet_tx diagnostic(.clk(sys_clk),.reset_n(reset_n),.valid(diagnostic_event),.ready(diagnostic_ready),.kind(8'd6),
   .session(active_session),.seq(output_step),.length(7'd64),.payload(diagnostic_payload),.byte_valid(diagnostic_byte_valid),.byte_ready(diagnostic_byte_ready),.byte_data(diagnostic_byte));
 fly01_uart_tx #(.CLKS_PER_BIT(UART_DIV)) diagnostic_uart(.clk(sys_clk),.reset_n(reset_n),.valid(diagnostic_byte_valid),.ready(diagnostic_byte_ready),.data(diagnostic_byte),.tx(uart_txd));
 assign led={fault||i2c_fault,armed,usable,seen};
 always @(posedge sys_clk)begin
  if(!reset_n)begin
   active_session<=0;last_seq<=0;age<=AGE_CYCLES;request_timer<=0;seen<=0;usable<=0;armed<=0;core_reset<=0;
   observation_mask<=0;observation_mask_valid<=0;motion_activity<=0;
   observation_valid<=0;observation_usable<=0;observation_group<=0;observation_age_ms<=0;observation_session<=0;observation_source_seq<=0;
   noise_valid<=0;noise_mask<=0;noise_step<=0;noise_session<=0;request_valid<=0;result_age<=AGE_CYCLES;result_eligible<=0;enable_min_step<=0;
   initialized<=0;noise_consumed<=0;consumed_step<=0;
   observation_queue_cycles<=0;
   observation_overwrites<=0;diagnostic_drops<=0;previous_flags<=0;
  end else begin
   core_reset<=0;request_valid<=0;
   previous_flags<=flags;
   if(diagnostic_event&&!diagnostic_ready)diagnostic_drops<=diagnostic_drops+1;
   if(observation_valid&&observation_queue_cycles<AGE_CYCLES)observation_queue_cycles<=observation_queue_cycles+1;
   if(age<AGE_CYCLES)age<=age+1;
   if(result_age<AGE_CYCLES)result_age<=result_age+1;
   if(disarm_now||result_age>=AGE_CYCLES||bench_active||bench_request||
      i2c_retry_pending||i2c_retry_reset||i2c_fault||!i2c_zero_ack)armed<=0;
   else if(pc_valid&&pc_data=="E"&&!trim_receiving)begin armed<=1;enable_min_step<=model_step;end
   if(output_valid)begin result_eligible<=adopted_usable&&adopted_session==active_session;
     result_age<=adopted_age_cycles;end
   if(observation_valid&&observation_ready)begin observation_valid<=0;initialized<=1;end
   if(noise_valid&&noise_ready)begin noise_valid<=0;noise_consumed<=1;consumed_step<=noise_step;end
   if(new_obs)begin
     if(session_change)begin active_session<=session;seen<=1;last_seq<=seq;usable<=0;core_reset<=1;noise_valid<=0;observation_valid<=0;initialized<=0;noise_consumed<=0;motion_activity<=0;end
     else if(seq>last_seq)begin
       last_seq<=seq;usable<=!invalid_obs;motion_activity<=v2?payload[1]:!invalid_obs;
       observation_mask_valid<=v2;observation_mask<=incoming_mask;age<=payload[31:16]*(CLOCK_HZ/1000);
       if(observation_valid&&!observation_ready)observation_overwrites<=observation_overwrites+1;
       observation_valid<=1;observation_usable<=!invalid_obs;observation_group<=payload[9:8];observation_age_ms<=payload[31:16];
       observation_session<=session;observation_source_seq<=seq;
       observation_queue_cycles<=0;
     end
   end
   if(packet_valid&&kind==2&&length==59&&session==active_session&&seq==model_step&&!payload[471]&&!noise_valid&&initialized&&!(noise_consumed&&consumed_step==seq))begin
     noise_valid<=1;noise_step<=seq;noise_session<=session;noise_mask<=payload[470:0];
   end
   if(request_timer>=(CLOCK_HZ/1000)*20)begin
     request_timer<=0;
     if(seen&&initialized&&!noise_valid&&packet_tx_ready&&!(noise_consumed&&consumed_step==model_step))request_valid<=1;
   end else request_timer<=request_timer+1;
  end
 end
endmodule
