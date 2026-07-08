%% IMPORTANT: If the Software includes one or more computer programs bearing a Keysight copyright notice and in source code format (â€œSource Filesâ€?),
%% such Source Files are subject to the terms and conditions of the Keysight Software End-User License Agreement (â€œEULAâ€?) www.Keysight.com/find/sweula and these Supplemental Terms.
%% BY USING THE SOURCE FILES, YOU AGREE TO BE BOUND BY THE TERMS AND CONDITIONS OF THE EULA INCLUDING THESE SUPPLEMENTAL TERMS. IF YOU DO NOT AGREE TO THESE TERMS AND CONDITIONS,
%% DO NOT COPY OR DISTRIBUTE THE SOURCE FILES.
%%    1.	Additional Rights and Limitations. If Source Files are included with the Software, Keysight grants you a limited, non-exclusive license, without a right to sub-license,
%%          to copy, modify and distribute the Source Files solely in conjunction with Keysight instruments.
%%    2.	Distribution Requirements. Any distribution of the Source Files, unmodified or modified, to an external party shall be in conjunction with distribution of your system or
%%          product and shall be pursuant to an enforceable agreement that provides similar protections for Keysight and its suppliers as those contained in the EULA and these Supplemental Terms.
%%    3.	General. Capitalized terms used in these Supplemental Terms and not otherwise defined herein shall have the meanings assigned to them in the EULA. To the extent that any of these
%%          Supplemental Terms conflict with terms in the EULA, these Supplemental Terms control solely with respect to the Source Files.

function varargout = iqmain(varargin)
% IQMAIN M-file for iqmain.fig
%      IQMAIN, by itself, creates a new IQMAIN or raises the existing
%      singleton*.
%
%      H = IQMAIN returns the handle to a new IQMAIN or the handle to
%      the existing singleton*.
%
%      IQMAIN('CALLBACK',hObject,eventData,handles,...) calls the local
%      function named CALLBACK in IQMAIN.M with the given input arguments.
%
%      IQMAIN('Property','Value',...) creates a new IQMAIN or raises the
%      existing singleton*.  Starting from the left, property value pairs are
%      applied to the GUI before iqmain_OpeningFcn gets called.  An
%      unrecognized property name or invalid value makes property application
%      stop.  All inputs are passed to iqmain_OpeningFcn via varargin.
%
%      *See GUI Options on GUIDE's Tools menu.  Choose "GUI allows only one
%      instance to run (singleton)".
%
% See also: GUIDE, GUIDATA, GUIHANDLES

% Edit the above text to modify the response to help iqmain

% Last Modified by GUIDE v2.5 12-Nov-2025 22:49:43

% Begin initialization code - DO NOT EDIT
gui_Singleton = 1;
gui_State = struct('gui_Name',       mfilename, ...
                   'gui_Singleton',  gui_Singleton, ...
                   'gui_OpeningFcn', @iqmain_OpeningFcn, ...
                   'gui_OutputFcn',  @iqmain_OutputFcn, ...
                   'gui_LayoutFcn',  [] , ...
                   'gui_Callback',   []);
if nargin && ischar(varargin{1})
    gui_State.gui_Callback = str2func(varargin{1});
end

if nargout
    [varargout{1:nargout}] = gui_mainfcn(gui_State, varargin{:});
else
    gui_mainfcn(gui_State, varargin{:});
end
% End initialization code - DO NOT EDIT


% --- Executes just before iqmain is made visible.
function iqmain_OpeningFcn(hObject, eventdata, handles, varargin)
% This function has no output args, see OutputFcn.
% hObject    handle to figure
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
% varargin   command line arguments to iqmain (see VARARGIN)

% Choose default command line output for iqmain
handles.output = hObject;
% Update handles structure
guidata(hObject, handles);
% compiled code seems to start up in windows\system32. That's not good...
if (isdeployed)
    [~, result] = system('path');
    cd(char(regexpi(result, 'Path=(.*?);', 'tokens', 'once')));
end
update_gui(hObject, [], handles);

% Show version at the bottom of the main window:
if (isdeployed())
    suffix = ' (compiled) ';
    % in compiled mode, always log SCPI commands - simplifies debugging
    assignin('base', 'debugScpi', 1);
else
    suffix = ' (script) ';
end

versionNumFile = fopen('iqversionNum.txt', 'r');
versionNum = fgetl(versionNumFile);
fclose(versionNumFile);

versionDate = iqversionDate(); % format yyyy.mm.dd

set(handles.bottomText, 'String', [versionNum suffix versionDate]);

% temporary Workaround for MATLAB 2025
iqCheckWidgets(hObject);

% UIWAIT makes iqmain wait for user response (see UIRESUME)
% uiwait(handles.iqtool);


% --- Outputs from this function are returned to the command line.
function varargout = iqmain_OutputFcn(hObject, eventdata, handles)
% varargout  cell array for returning output args (see VARARGOUT);
% hObject    handle to figure
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Get default command line output from handles structure
varargout{1} = handles.output;


% --- Executes on button press in pushbuttonSerial.
function pushbuttonSerial_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonSerial (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();
launchTool(handles, 'Serial Data', @iserial_gui);

% --- Executes on button press in pushbuttonConfig.
function pushbuttonConfig_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonConfig (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
iqconfig();

% --- Executes on button press in pushbuttonTone.
function pushbuttonTone_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonTone (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
launchTool(handles, 'Multi-Tone & Noise', @iqtone_gui);


% --- Executes on button press in pushbuttonMod.
function pushbuttonMod_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonMod (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
launchTool(handles, 'Digital Modulations', @iqmod_gui);


% --- Executes on button press in pushbuttonDPMod.
function pushbuttonDPMod_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonDPMod (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
%iqmod_gui('DP');
launchTool(handles, 'Dual Pol. Digital Modulations', @iqmod_gui, 'DP');


% --- open a tool window of which multiple copies are allowed
function launchTool(~, name, fcn, param)
TempHide = get(0, 'ShowHiddenHandles');
set(0, 'ShowHiddenHandles', 'on');
figs = findobj(0, 'Type', 'figure', 'Name', name);
set(0, 'ShowHiddenHandles', TempHide);
% if it is not open at all, open it
if (isempty(figs))
    if exist('param', 'var')
        fcn(param);
    else
        fcn();
    end
else
    % bring the existing ones on screen
    for i = 1:length(figs)
        fig = figs(i);
        fig.WindowState = 'normal';
        % toggling visibility brings it to the top
        fig.Visible = 'off';
        fig.Visible = 'on';
    end
    res = questdlg(sprintf(['Would you like to open another copy of the "%s" window, ' ...
        'e.g. to load a different waveform in each channel?'], name), 'New window?', 'Yes', 'No', 'Yes');
    if strcmp(res, 'Yes')
        fig = figs(1);
        pos = get(fig, 'Position');
        pos(1) = pos(1) + pos(3);
        if exist('param', 'var')
            fig2 = fcn(param); % cannot pass a parameter and set position at the same time
        else
            fig2 = fcn('Position', pos);
        end
        fig2.Position = pos;
        %fig2 = fcn('Position', pos); % place new window next to existing one
        copyContent(fig, fig2);
    end
end


function copyContent(h, h2)
% recursively walk through he GUI elements and save the properties
type = get(h, 'Type');
if (strcmp(type, 'uicontrol'))
    style = get(h, 'Style');
    switch (style)
        case { 'edit',  'text', 'pushbutton' }
            set(h2, 'Visible', get(h, 'Visible'));
            set(h2, 'Enable', get(h, 'Enable'));
            set(h2, 'String', get(h, 'String'));
            set(h2, 'UserData', get(h, 'UserData'));
        case { 'checkbox', 'slider', 'radiobutton' }
            set(h2, 'Visible', get(h, 'Visible'));
            set(h2, 'Enable', get(h, 'Enable'));
            set(h2, 'Value', get(h, 'Value'));
        case { 'popupmenu' }
            set(h2, 'Visible', get(h, 'Visible'));
            set(h2, 'Enable', get(h, 'Enable'));
            set(h2, 'String', get(h, 'String'));
            set(h2, 'Value', get(h, 'Value'));
        otherwise
            fprintf('unknown style/tag: %s - %s\n', get(h, 'Style'),  get(h, 'Tag'));
    end
elseif (strcmp(type, 'uitable'))
    set(h2, 'Data', get(h, 'Data'));
    set(h2, 'ColumnFormat', get(h, 'ColumnFormat'));
elseif (strcmp(type, 'uimenu'))
    set(h2, 'Checked', get(h, 'Checked'));
end
% descend to next level of children
hc = get(h, 'Children');
h2c = get(h2, 'Children');
for hi = 1:length(hc)
    copyContent(hc(hi), h2c(hi));
end

function pushbuttonFsk_Callback(hObject, eventdata, handles)
loadArbConfig();    % make sure arbConfig exists
iqfsk();

% --- Executes on button press in pushbuttonPulse.
function pushbuttonPulse_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonPulse (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
launchTool(handles, 'Radar pulses & frequency chirps', @iqpulse_gui);


% --- Executes on button press in pushbuttonLoadFile.
function pushbuttonLoadFile_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonLoadFile (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
iqloadfile();


% --- Executes on button press in pushbuttonOFDM.
function pushbuttonOFDM_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonOFDM (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
iqofdm();


% --- Executes on button press in pushbuttonPulseGen.
function pushbuttonPulseGen_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonPulseGen (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
launchTool(handles, 'Function Generator', @iqpulsegen_gui);


% --- Executes on button press in pushbuttonSequencer.
function pushbuttonSequencer_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonSequencer (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
arbConfig = loadArbConfig();    % make sure arbConfig exists
if contains(arbConfig.model, 'M8198A')
    launchTool(handles, 'Sequence Setup for M8198A', @iqseq_M8198A_gui);
else
    iqseq();
end


% --- Executes on button press in pushbuttonCATV.
function pushbuttonCATV_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonCATV (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
catv_gui();


% --- Executes on button press in pushbuttonRadarDemo.
function pushbuttonRadarDemo_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonRadarDemo (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
iqrsim_gui();


% --- Executes on button press in pushbuttonSeqDemo1.
function pushbuttonSeqDemo1_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonSeqDemo1 (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
%seqtest1_gui();
seqtestAll_gui();

% --- Executes on button press in pushbuttonM8190ADemos.
function pushbuttonM8190ADemos_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonM8190ADemos (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% if iqmain.fig is opened directly, then handles is empty and we have to
% find a workaround to access the other GUI elements
if (isfield(handles, 'AWGSpecificFunctions') && handles.AWGSpecificFunctions == 1)
    handles.AWGSpecificFunctions = 0;
else
    handles.AWGSpecificFunctions = 1;
end
guidata(hObject, handles);
update_gui(hObject, eventdata, handles);



function result = checkfields(hObject, eventdata, handles)
% This function verifies that all the fields have valid and consistent
% values. It is called from inside this script as well as from the
% iqconfig script when arbConfig changes (i.e. a different model or mode is
% selected). Returns 1 if all fields are OK, otherwise 0
result = 1;
update_gui(hObject, eventdata, handles);


function update_gui(hObject, eventdata, handles)
% retrieve handles again, in case this function is called from iqconfig
handles = guidata(hObject);
if (isempty(handles))
    % if iqtools was launched by double clicking on iqmain.fig, the
    % "handles" structure is not initialized. Workaround: restart it.
    close(hObject);
    iqmain();
    return;
end
% find out if arbConfig.mat is available.  If not, don't complain ...
% it could be the first start of iqmain and arbConfig does not exist
try
    load(iqarbConfigFilename());
    arbConfig = loadArbConfig();
catch e
    arbConfig = [];
end
if (~isempty(arbConfig))
    if (~isempty(strfind(arbConfig.model, 'M8190')))
        set(handles.pushbuttonM8190ADemos, 'String', regexprep(get(handles.pushbuttonM8190ADemos, 'String'), '.*specific', 'M8190A specific'));
        set(handles.pushbuttonM8190ADemos, 'Enable', 'on');
        set(handles.uipanelM8190A, 'Visible', 'on');
        set(handles.uipanelM8195A, 'Visible', 'off');
        set(handles.uipanelM8196A, 'Visible', 'off');
        set(handles.uipanelM8121A, 'Visible', 'off');
    elseif (~isempty(strfind(arbConfig.model, 'M8195')))
        set(handles.pushbuttonM8190ADemos, 'String', regexprep(get(handles.pushbuttonM8190ADemos, 'String'), '.*specific', 'M8195A specific'));
        set(handles.pushbuttonM8190ADemos, 'Enable', 'on');
        set(handles.uipanelM8190A, 'Visible', 'off');
        set(handles.uipanelM8196A, 'Visible', 'off');
        set(handles.uipanelM8121A, 'Visible', 'off');
        set(handles.uipanelM8195A, 'Visible', 'on');
        pos = get(handles.uipanelM8190A, 'Position');
        set(handles.uipanelM8195A, 'Position', pos);
    elseif (~isempty(strfind(arbConfig.model, 'M8196')) || ~isempty(strfind(arbConfig.model, 'M8194')))
        set(handles.pushbuttonM8190ADemos, 'String', regexprep(get(handles.pushbuttonM8190ADemos, 'String'), '.*specific', 'M8196A specific'));
        set(handles.pushbuttonM8190ADemos, 'Enable', 'on');
        set(handles.uipanelM8190A, 'Visible', 'off');
        set(handles.uipanelM8195A, 'Visible', 'off');
        set(handles.uipanelM8121A, 'Visible', 'off');
        set(handles.uipanelM8196A, 'Visible', 'on');
        pos = get(handles.uipanelM8190A, 'Position');
        set(handles.uipanelM8196A, 'Position', pos);
    elseif (~isempty(strfind(arbConfig.model, 'M8121A')))
        set(handles.pushbuttonM8190ADemos, 'String', regexprep(get(handles.pushbuttonM8190ADemos, 'String'), '.*specific', 'M8121A specific'));
        set(handles.pushbuttonM8190ADemos, 'Enable', 'on');
        set(handles.uipanelM8190A, 'Visible', 'off');
        set(handles.uipanelM8195A, 'Visible', 'off');
        set(handles.uipanelM8196A, 'Visible', 'off');
        set(handles.uipanelM8121A, 'Visible', 'on');
        pos = get(handles.uipanelM8190A, 'Position');
        set(handles.uipanelM8121A, 'Position', pos);
    else
        set(handles.pushbuttonM8190ADemos, 'Enable', 'off');
    end
end
figure = handles.iqtool;
pos = get(figure, 'Position');
if (isfield(handles, 'AWGSpecificFunctions') && handles.AWGSpecificFunctions && ~isempty(arbConfig) && ...
        (~isempty(strfind(arbConfig.model, 'M8190')) || ...
         ~isempty(strfind(arbConfig.model, 'M8195')) || ...
         ~isempty(strfind(arbConfig.model, 'M8196')) || ...
         ~isempty(strfind(arbConfig.model, 'M8194')) || ...
         ~isempty(strfind(arbConfig.model, 'M8121'))))
    pos(3) = 472;
    set(figure, 'Position', pos);
    set(handles.pushbuttonM8190ADemos, 'String', regexprep(get(handles.pushbuttonM8190ADemos, 'String'), '>', '<'));
else
    pos(3) = 241;
    set(figure, 'Position', pos);
    set(handles.pushbuttonM8190ADemos, 'String', regexprep(get(handles.pushbuttonM8190ADemos, 'String'), '<', '>'));
    set(handles.uipanelM8190A, 'Visible', 'off');
    set(handles.uipanelM8195A, 'Visible', 'off');
    set(handles.uipanelM8196A, 'Visible', 'off');
    set(handles.uipanelM8121A, 'Visible', 'off');
end


% --- Executes on button press in pushbuttonMultiChannel.
function pushbuttonMultiChannel_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonMultiChannel (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
multi_channel_sync_gui


% --- Executes on button press in pushbuttonDUCDemo.
function pushbuttonDUCDemo_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonDUCDemo (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
duc_ctrl();


% --- Executes on button press in pushbuttonMultiPulse.
function pushbuttonMultiPulse_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonMultiPulse (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
multi_pulse_gui();


% --- Executes on button press in pushbuttonCPHY.
function pushbuttonCPHY_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonCPHY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
dphy();


% --- Executes on button press in pushbuttonKeysight.
function pushbuttonKeysight_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonKeysight (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
keysight_gui();


% --- Executes on button press in pushbuttonKeysightM8195A.
function pushbuttonKeysightM8195A_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonKeysightM8195A (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
keysight_gui();


% --- Executes on button press in pushbutton16chanSync.
function pushbutton16chanSync_Callback(hObject, eventdata, handles)
% hObject    handle to pushbutton16chanSync (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
multi_16channel_sync_gui


% --- Executes on button press in pushbuttonPulseDemo.
function pushbuttonPulseDemo_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonPulseDemo (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
mpulse_demo();


% --- Executes on button press in pushbuttonFIR.
function pushbuttonFIR_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonFIR (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
arbConfig = loadArbConfig();    % make sure arbConfig exists
if (strcmp(arbConfig.model, 'M8195A_Rev1'))
    errordlg('FIR filters are not available in M8195A Rev. 1');
    return;
end
iqfir();


% --- Executes on button press in pushbuttonENOB
function pushbuttonENOB_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonENOB (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
iqenob();


% --- Executes on button press in pushbuttonMMA_demo.
function pushbuttonMMA_demo_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonMMA_demo (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
mma_demo();


% --- Executes on button press in pushbuttonCalTone.
function pushbuttonCalTone_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonCalTone (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
iqcaltone();


% --- Executes on button press in pushbuttonAoA.
function pushbuttonAoA_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonAoA (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();
iqaoademo();


% --- Executes on button press in pushbuttonNoiseSeq.
function pushbuttonNoiseSeq_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonNoiseSeq (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();
iqnoiseseq();


% --- Executes on button press in pushbuttonInSystemCal.
function pushbuttonInSystemCal_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonInSystemCal (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();
iqmtcal();


% --- Executes on button press in pushbuttonFMCWRadar.
function pushbuttonFMCWRadar_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonFMCWRadar (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();
if (~isdeployed)
    mypath = fullfile(fileparts(which('iqmain')), 'FMCWRadar');
    addpath(mypath);
end
FMCWRadarGui


% --- Executes on button press in pushbuttonRadarDemoM8195A.
function pushbuttonRadarDemoM8195A_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonRadarDemoM8195A (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();
iqrsim();

% --- Executes on button press in pushbuttonMultiPulse.
function pushbuttonMultiPulseM8121A_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonMultiPulse (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();
multi_pulse();


% --- Executes on button press in pushbuttonKandou.
function pushbuttonKandou_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonKandou (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();
iqkandou_gui();


% --- Executes on button press in pushbuttonDistortion.
function pushbuttonDistortion_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonDistortion (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();
iqdistgen_gui();


% --------------------------------------------------------------------
function menuShowCorrection_Callback(hObject, eventdata, handles)
% hObject    handle to menuShowCorrection (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
iqcorrmgmt();


% --------------------------------------------------------------------
function menuRadarToSound_Callback(hObject, eventdata, handles)
% hObject    handle to menuRadarToSound (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
iqtosound_gui();


% --------------------------------------------------------------------
function menuDrawIQ_Callback(hObject, eventdata, handles)
% hObject    handle to menuRadarToSound (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
iqdraw_gui();


% --------------------------------------------------------------------
function pushbuttonPicSpec_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonPicSpec (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
if (iqoptcheck([], {'M8190A_12bit', 'M8190A_14bit', 'M8195A_1ch', 'M8195A_1ch_mrk', 'M8195A_2ch', 'M8195A_2ch_mrk', 'M8195A_2ch_dupl','M8195A_1ch_dupl' 'M8195A_4ch'}, 'SEQ'))
    iqpicspec();
end


% --------------------------------------------------------------------
function menuHelpAbout_Callback(hObject, eventdata, handles)
% hObject    handle to menuHelpAbout (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
try
    iqHelpAbout();
catch ex
    msgbox(sprintf('Can not open iqHelpAbout:\n%s', ex.message));
end


% --------------------------------------------------------------------
function menuDualPolDigMod_Callback(hObject, eventdata, handles)
% hObject    handle to menuDualPolDigMod (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
loadArbConfig();    % make sure arbConfig exists
%iqmod_gui('DP');
launchTool(handles, 'Dual Pol. Digital Modulations', @iqmod_gui, 'DP');


% --------------------------------------------------------------------
function menuXYimage_Callback(hObject, eventdata, handles)
% hObject    handle to menuXYimage (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
iqxyimage_gui();
