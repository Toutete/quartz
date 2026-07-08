

function [OSA] = init_AQ6370(wl,span,OSA_gpib);  % YOKOGAWA

vender = 'ni';
gpib_adrr = 0; 
OSA = gpib(vender,gpib_adrr ,OSA_gpib);   %ADNO AQ6317, using NI GPIB

OSA.InputBufferSize = 51200; 
OSA.OutputBufferSize = 51200; 


fopen(OSA);

% initialize OSA and wavelength setting 

fprintf(OSA,'MKCL');  % all marker clear; 

fprintf(OSA,[':sens:wav:cent ',num2str(wl),'nm'] );  % all marker clear; 
fprintf(OSA,[':sens:wav:span ',num2str(span),'nm'] );  % all marker clear; 
pause(0.5);

% fprintf(OSA,'SGL');  % single sweep 
% pause(10);  % wating for single sweep 

% fclose(OSA); 


end