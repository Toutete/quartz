

instrreset;

% for AQ6370D YOKOGAWA
wl = 1550.1 ;  % center wavelength 
span = 1 ;  % span
res = .02 ;  % resolution BW; 
OSA_gpib = 1; 


[OSA]= init_AQ6370(wl,span,OSA_gpib);  % init_Q6370 

% single sweep 

fprintf(OSA,[':init:smode 1']);  % single sweep mode
fprintf(OSA,['*CLS']);  % status clear
fprintf(OSA,[':init']);  % run single swee 

pause(5);  % wait for the sweep 

OSA.InputBufferSize = 51200; 


xx=query(OSA,':TRAC:DATA:X? TRA');
yy=query(OSA,':TRAC:DATA:Y? TRA');

% convert char => double  
xx = split(xx,',');
yy = split(yy,',');
wavelength = zeros(1,length(xx));
power = zeros(1,length(yy));
for ii = 1 : length(xxx)
wavelength(1,ii) =  str2double(xx{ii,1}) ;
power(1,ii)  = str2double(yy{ii,1});
end


figure(1); plot(wavelength,power);