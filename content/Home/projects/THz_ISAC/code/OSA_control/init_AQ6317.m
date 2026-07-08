


function [OSA] = init_AQ6317(wl,span,OSA_gpib);

vender = 'ni';
gpib_adrr = 0; 
OSA = gpib(vender,gpib_adrr ,OSA_gpib);   %ADNO AQ6317, using NI GPIB
fopen(OSA);

% initialize OSA and wavelength setting 

fprintf(OSA,'MKCL');  % all marker clear; 

fprintf(OSA,strcat('CTRWL',num2str(wl)));  % set center WL
fprintf(OSA,strcat('SPAN',num2str(span))); % set span WL
pause(0.5);

% fprintf(OSA,'SGL');  % single sweep 
% pause(10);  % wating for single sweep 

% fclose(OSA); 


end