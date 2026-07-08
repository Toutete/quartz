%% IMPORTANT: If the Software includes one or more computer programs bearing a Keysight copyright notice and in source code format ("Source Files"),
%% such Source Files are subject to the terms and conditions of the Keysight Software End-User License Agreement ("EULA") www.Keysight.com/find/sweula and these Supplemental Terms.
%% BY USING THE SOURCE FILES, YOU AGREE TO BE BOUND BY THE TERMS AND CONDITIONS OF THE EULA INCLUDING THESE SUPPLEMENTAL TERMS. IF YOU DO NOT AGREE TO THESE TERMS AND CONDITIONS, 
%% DO NOT COPY OR DISTRIBUTE THE SOURCE FILES.
%%    1.	Additional Rights and Limitations. If Source Files are included with the Software, Keysight grants you a limited, non-exclusive license, without a right to sub-license, 
%%          to copy, modify and distribute the Source Files solely in conjunction with Keysight instruments.
%%    2.	Distribution Requirements. Any distribution of the Source Files, unmodified or modified, to an external party shall be in conjunction with distribution of your system or 
%%          product and shall be pursuant to an enforceable agreement that provides similar protections for Keysight and its suppliers as those contained in the EULA and these Supplemental Terms. 
%%    3.	General. Capitalized terms used in these Supplemental Terms and not otherwise defined herein shall have the meanings assigned to them in the EULA. To the extent that any of these 
%%          Supplemental Terms conflict with terms in the EULA, these Supplemental Terms control solely with respect to the Source Files.

function varargout = iqmod_gui(varargin)
% IQMOD_GUI M-file for iqmod_gui.fig
%      IQMOD_GUI, by itself, creates a new IQMOD_GUI or raises the existing
%      singleton*.
%
%      H = IQMOD_GUI returns the handle to a new IQMOD_GUI or the handle to
%      the existing singleton*.
%
%      IQMOD_GUI('CALLBACK',hObject,eventData,handles,...) calls the local
%      function named CALLBACK in IQMOD_GUI.M with the given input arguments.
%
%      IQMOD_GUI('Property','Value',...) creates a new IQMOD_GUI or raises the
%      existing singleton*.  Starting from the left, property value pairs are
%      applied to the GUI before iqmod_gui_OpeningFcn gets called.  An
%      unrecognized property name or invalid value makes property application
%      stop.  All inputs are passed to iqmod_gui_OpeningFcn via varargin.
%
%      *See GUI Options on GUIDE's Tools menu.  Choose "GUI allows only one
%      instance to run (singleton)".
%
% See also: GUIDE, GUIDATA, GUIHANDLES

% Edit the above text to modify the response to help iqmod_gui

% Last Modified by GUIDE v2.5 09-Dec-2025 12:52:54

% Begin initialization code - DO NOT EDIT
gui_Singleton = 0;
gui_State = struct('gui_Name',       mfilename, ...
                   'gui_Singleton',  gui_Singleton, ...
                   'gui_OpeningFcn', @iqmod_gui_OpeningFcn, ...
                   'gui_OutputFcn',  @iqmod_gui_OutputFcn, ...
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


% --- Executes just before iqmod_gui is made visible.
function iqmod_gui_OpeningFcn(hObject, eventdata, handles, varargin)
% This function has no output args, see OutputFcn.
% hObject    handle to figure
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
% varargin   command line arguments to iqmod_gui (see VARARGIN)

% temporary workaround for MATLAB 2025
iqCheckWidgets(hObject);

% Choose default command line output for iqmod_gui
handles.output = hObject;
handles.os_resolution = 0.0005;
% Update handles structure
guidata(hObject, handles);

if length(varargin) >= 1 && ischar(varargin{1}) && strcmp(varargin{1}, 'DP')
    set(handles.menuDualPolarization, 'Checked', 'on');
    set(hObject, 'Name', 'Dual Pol. Digital Modulations');
end

% make sure the modulation type popup is saved incl. the strings
% This is because "Custom" format is added dynamically
set(handles.popupmenuModType, 'UserData', 'saveList');

arbConfig = loadArbConfig();
switch arbConfig.model
    case {'M8190A_14bit'}
        oversampling = 8;
        offset = 2e9;
    case 'M8190A_12bit'
        oversampling = 8;
        offset = 2e9;
    case {'M8195A_Rev0', 'M8195A_Rev1'}
        set(handles.editNumSymbols, 'String', '4000');
        oversampling = 4;
        offset = 0;
    case 'AWG7xxxx'
        offset = 5e9;
        oversampling = 10;
    case 'M8135A'
        oversampling = 4;
        offset = 0;
        set(handles.menuUSPAVSA, 'Visible', 'on')
    otherwise
        oversampling = 4;
        offset = 0;
        set(handles.menuUSPAVSA, 'Visible', 'off')
end
set(handles.editFilename, 'Position', get(handles.editData, 'Position'));
set(handles.editFilenameY, 'Position', get(handles.editDataY, 'Position'));
set(handles.editCustomPrbs, 'Position', get(handles.editData, 'Position'));
set(handles.editCustomPrbsY, 'Position', get(handles.editDataY, 'Position'));
set(handles.popupmenuPrbs, 'Position', get(handles.editData, 'Position'));
set(handles.popupmenuPrbsY, 'Position', get(handles.editDataY, 'Position'));
set(handles.editSampleRate, 'String', iqengprintf(arbConfig.defaultSampleRate));
set(handles.popupmenuModType, 'Value', 8);  % QAM16
set(handles.editOversampling, 'String', num2str(oversampling));
set(handles.editSymbolRate, 'String', iqengprintf(arbConfig.defaultSampleRate / oversampling));
if (isfield(arbConfig, 'defaultFc') && arbConfig.defaultFc ~= 0)
    set(handles.editCarrierOffset, 'String', iqengprintf(0));
    set(handles.editFc, 'String', iqengprintf(arbConfig.defaultFc));
elseif (~isempty(strfind(arbConfig.model, 'DUC')) && ...
    isfield(arbConfig, 'carrierFrequency'))
    set(handles.editCarrierOffset, 'String', iqengprintf(0));
    set(handles.editFc, 'String', iqengprintf(arbConfig.carrierFrequency));
else
    set(handles.editCarrierOffset, 'String', iqengprintf(offset));
    set(handles.editFc, 'String', iqengprintf(offset));
end
prbsList = {'x^7 + x^1 + 1', 'x^9 + x^5 + 1', 'x^10 + x^3 + 1', 'x^11 + x^9 + 1', ...
            'x^12 + x^11 + x^8 + x^6 + 1', 'x^13 + x^12 + x^11 + 1', 'x^15 + x^1 + 1' };
set(handles.popupmenuPrbs, 'String', prbsList);
set(handles.popupmenuPrbsY, 'String', prbsList);
set(handles.popupmenuPrbs, 'Userdata', 'saveList');
set(handles.popupmenuPrbsY, 'Userdata', 'saveList');
% update all the fields
popupmenuData_Changed(handles);
checkfields([], 0, handles);

if (~isfield(arbConfig, 'tooltips') || arbConfig.tooltips == 1)
set(handles.editSampleRate, 'TooltipString', sprintf([ ...
    'This field defines the AWG sample rate in Hertz. By default, it will be\n' ...
    'set automatically, but the value can be overwritten if a specific sample\n' ...
    'rate is desired']));
set(handles.editOversampling, 'TooltipString', sprintf([ ...
    'This field defines the ratio of sampling rate vs. symbol rate.\n' ...
    'Integer and fractional values are supported. Normally it is not necessary\n' ...
    'to set this field since it will be automatically calculated based on\n' ...
    'sampling rate and symbol rate.']));
set(handles.editSymbolRate, 'TooltipString', sprintf([ ...
    'This field defines the symbol rate (= toggle rate) of the modulated signal.\n']));
set(handles.editNumSymbols, 'TooltipString', sprintf([ ...
    'The utility will generate the given number of random symbols.\n' ...
    'A larger number will give a more realistic spectral shape but\n' ...
    'will also increase computation time. Especially when using large\n' ...
    'oversampling factors (> 20), start with a small number of symbols\n' ...
    '(e.g. 20) to keep the computation time within reasonable limits.\n' ...
    'Then gradually increase the number. Computation time can be reduced\n' ...
    'by using a number that is a multiple of the AWG''s segment granularity.']));
set(handles.popupmenuModType, 'TooltipString', sprintf([ ...
    'Select the modulation scheme for the digital modulation.\n' ...
    'When using high symbol rates (> 1 GSym/s), start with a lower order\n' ...
    'modulation scheme (e.g. QPSK) and make sure it is decoded correctly\n' ...
    'and perform a magnitude/phase calibration using this scheme.\n' ...
    'Then switch to higher order modulation schemes.']));
set(handles.popupmenuFilter, 'TooltipString', sprintf([ ...
    'Select the pulse shaping filter that will be applied to the modulated\n' ...
    'baseband signal. Root raised cosine is the default and should normally\n' ...
    'be used except for experimental purposes.']));
set(handles.pushbuttonCalibrate, 'TooltipString', sprintf([ ...
    'This button uses the VSA software to perform a magnitude and phase\n' ...
    'calibration. After pressing this button, the VSA software will be started\n' ...
    '(if it is not already running) and automatically configured with the parameters\n' ...
    'in this utility. The equalizer in the VSA software is turned on and determines\n' ...
    'the frequency and phase response of the channel. After the equalizer has\n' ...
    'stabilized, you can press the OK button to generate a calibration file.\n' ...
    'Once the file has been created, pre-distortion is automatically applied\n' ...
    'to the original signal, the pre-distorted waveform is downloaded into the\n' ...
    'AWG and the equalizer in the VSA software is turned off.\n\n' ...
    'Please verify that you have the VSA calibration parameters (in particular\n' ...
    '"Fc" set to the correct value before starting the calibration process.']));
set(handles.editFc, 'TooltipString', sprintf([ ...
    'Set the center frequency that is used by the VSA software during calibration.\n' ...
    'Whenever the Carrier Offset parameter is modified, it will be copied into\n' ...
    'this field, but it can be changed afterwards. This is necessary in those cases\n' ...
    'where the output of the AWG is not analyzed directly, but is up-converted using\n' ...
    'an external I/Q modulator or mixer.']));
set(handles.checkboxCorrection, 'TooltipString', sprintf([ ...
    'Use this checkbox to pre-distort the signal using the previously established\n' ...
    'calibration values. Calibration can be performed using the multi-tone or\n' ...
    'digital modulation utilities.']));
set(handles.pushbuttonShowCorrection, 'TooltipString', sprintf([ ...
    'Use this button to visualize the frequency and phase response that has\n' ...
    'been captured using the "Calibrate" functionality in the multi-tone or\n' ...
    'digital modulation utility. In multi-tone, only magnitude corrections\n' ...
    'are captured whereas in digital modulation, both magnitude and phase\n' ...
    'response are calculated.']));
set(handles.editFilterNsym, 'TooltipString', sprintf([ ...
    'Set the filter length of the pulse shaping filter in units of symbols.\n']));
set(handles.editFilterBeta, 'TooltipString', sprintf([ ...
    'Set the filter roll-off for the pulse shaping filter.\n']));
set(handles.editQuadErr, 'TooltipString', sprintf([ ...
    'Set the quadrature error in degrees. Valid range is -360...+360 degrees.\n']));
set(handles.editQuadErrY, 'TooltipString', sprintf([ ...
    'Set the quadrature error in degrees. Valid range is -360...+360 degrees.\n']));
set(handles.editIQSkew, 'TooltipString', sprintf([ ...
    'Set the IQ Skew in units of seconds.\n' ...
    'Positive values will delay the I component relative to Q\n']));
set(handles.editIQSkewY, 'TooltipString', sprintf([ ...
    'Set the IQ Skew in units of seconds.\n' ...
    'Positive values will delay the I component relative to Q\n']));
set(handles.editGainImbalance, 'TooltipString', sprintf([ ...
    'Set the gain imbalance in units of db.\n' ...
    'Positive values will amplify I vs. Q. Negative values will attenuate I vs. Q.\n']));
set(handles.editGainImbalanceY, 'TooltipString', sprintf([ ...
    'Set the gain imbalance in units of db.\n' ...
    'Positive values will amplify I vs. Q. Negative values will attenuate I vs. Q.\n']));
set(handles.editXYgainImbalance, 'TooltipString', sprintf([ ...
    'Set the X/Y gain imbalance in units of db.\n' ...
    'Positive values will amplify X vs. Y. Negative values will attenuate X vs. Y.\n']));
set(handles.editXYskew, 'TooltipString', sprintf([ ...
    'Set the X/Y skew in units of seconds.\n' ...
    'Positive values will delay X vs. Y.\nNegative values will delay Y vs. X.']));
set(handles.editCarrierSpacing, 'TooltipString', sprintf([ ...
    'Set the carrier spacing for multi-carrier signals.\n' ...
    'The carrier spacing must be larger than the symbol rate.\n' ...
    'Carrier frequencies start with "Carrier offset" and go up in\n' ...
    'steps of "Carrier Spacing".\n']));
set(handles.editCarrierOffset, 'TooltipString', sprintf([ ...
    'Set the carrier offset to 0 to generate a baseband I/Q signal.\n' ...
    'Set it to a value between zero and Fs/2 to perform digital upconversion\n' ...
    'to that center frequency. For a signal in the second Nyquist band,\n' ...
    'set the carrier offset to a value between Fs/2 and Fs. For multi-carrier\n' ...
    'signals, you can enter a list of frequencies or a single value that and\n' ...
    'defines the first (lowest) carrier offset.']));
set(handles.editMagnitudes, 'TooltipString', sprintf([ ...
    'Enter a list of magnitudes in dB. Each carrier will be assigned a\n' ...
    'magnitude from this list. If the list contains fewer values than\n' ...
    'carriers, the list will be used repeatedly.']));
set(handles.pushbuttonChannelMapping, 'TooltipString', sprintf([ ...
    'Select into which channels the real and imaginary part of the waveform\n' ...
    'is loaded. By default, I is loaded into Channel 1, Q into channel 2, but\n' ...
    'it is also possible to load the same signal into both channels.\n' ...
    'In DUC modes, both I and Q are used for the same channel.\n' ...
    'In dual-M8190A configurations, channels 3 and 4 are on the second module.']));
set(handles.editSegment, 'TooltipString', sprintf([ ...
    'Enter the AWG waveform segment to which the signal will be downloaded.\n' ...
    'If you download to segment #1, all other segments will be automatically\n' ...
    'deleted.']));
set(handles.pushbuttonDisplay, 'TooltipString', sprintf([ ...
    'Use this button to calculate and show the simulated waveform using MATLAB plots.\n' ...
    'The signal will be displayed both in the time- as well as frequency\n' ...
    'domain (spectrum). This function can be used even without any hardware\n' ...
    'connected.']));
set(handles.pushbuttonDownload, 'TooltipString', sprintf([ ...
    'Use this button to calculate and download the signal to the configured AWG.\n' ...
    'Make sure that you have configured the connection parameters in "Configure\n' ...
    'instrument connection" before using this function.']));
set(handles.editShift, 'TooltipString', sprintf([ ...
    'Enter the number of symbols by which this signal is (circularly) shifted.\n' ...
    'This functionality is useful to have a different signal on the X and Y\n' ...
    'polarization while still using the same PRBS polynomial.']));
set(handles.editShiftY, 'TooltipString', sprintf([ ...
    'Enter the number of symbols by which this signal is (circularly) shifted.\n' ...
    'This functionality is useful to have a different signal on the X and Y\n' ...
    'polarization while still using the same PRBS polynomial.']));
% set(handles.pushbuttonShowVSA, 'TooltipString', sprintf([ ...
%     'Use this button to calculate and visualize the signal using the VSA software.\n' ...
%     'No hardware access is required.\n' ...
%     'If the VSA software is not already running, it will be started. The utility will\n' ...
%     'automatically configure the VSA software for the parameters of the generated signal.\n' ...
%     'VSA versions 15 and higher are supported.']));
end
% UIWAIT makes iqmod_gui wait for user response (see UIRESUME)
% uiwait(handles.iqtool);


% --- Outputs from this function are returned to the command line.
function varargout = iqmod_gui_OutputFcn(hObject, eventdata, handles) 
% varargout  cell array for returning output args (see VARARGOUT);
% hObject    handle to figure
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Get default command line output from handles structure
varargout{1} = handles.output;



function editSampleRate_Callback(hObject, eventdata, handles)
% hObject    handle to editSampleRate (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editSampleRate as text
%        str2double(get(hObject,'String')) returns contents of editSampleRate as a double
value = [];
arbConfig = loadArbConfig();
try
    value = iqparse(get(handles.editSampleRate, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
if (isscalar(value) && (~isempty(find(value >= arbConfig.minimumSampleRate & value <= arbConfig.maximumSampleRate, 1))))
    symbolRate = iqparse(get(handles.editSymbolRate, 'String'), 'scalar');
    oversampling = value / symbolRate;
    % set the exact value temporarily - editOversampling_Callback will do
    % the rounding
    set(handles.editOversampling, 'String', iqengprintf(oversampling));
    editOversampling_Action([], eventdata, handles);
end
checkfields([], 0, handles);


% --- Executes during object creation, after setting all properties.
function editSampleRate_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editSampleRate (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editNumSamples_Callback(hObject, eventdata, handles)
% hObject    handle to editNumSamples (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editNumSamples as text
%        str2double(get(hObject,'String')) returns contents of editNumSamples as a double
value = [];
try
    value = iqparse(get(hObject, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
if (isscalar(value) && value >= 320 && value <= 64e6)
    oversampling = iqparse(get(handles.editOversampling, 'String'), 'scalar');
    numSymbols = iqparse(get(handles.editNumSymbols, 'String'), 'scalar');
    numSamples = iqparse(get(handles.editNumSamples, 'String'), 'scalar');
    numSymbols = round(numSamples / oversampling);
    numSamples = calcNumSamples(numSymbols, oversampling, handles);
    set(handles.editNumSymbols, 'String', num2str(numSymbols));
    set(handles.editNumSamples, 'String', num2str(numSamples));
    set(hObject,'BackgroundColor','white');
else
    set(hObject,'BackgroundColor','red');
end


function numSamples = calcNumSamples(numSymbols, oversampling, handles)
% find rational number to approximate the oversampling
[overN overD] = rat(oversampling, handles.os_resolution);
% adjust number of samples to match AWG limitations
arbConfig = loadArbConfig();
overD1 = gcd(overD, numSymbols);
numSamples = lcm(numSymbols * overN / overD1, arbConfig.segmentGranularity);
while (numSamples < arbConfig.minimumSegmentSize)
    numSamples = 2 * numSamples;
end
numSymbols = round(numSamples / overN * overD);



% --- Executes during object creation, after setting all properties.
function editNumSamples_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editNumSamples (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editOversampling_Callback(hObject, eventdata, handles)
editOversampling_Action(hObject, eventdata, handles);


%---------------------------------------------------------------------
function editOversampling_Action(hObject, eventdata, handles)
% hObject    handle to editOversampling (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editOversampling as text
%        str2double(get(hObject,'String')) returns contents of editOversampling as a double
oversampling = [];
try
    oversampling = iqparse(get(handles.editOversampling, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
if (isscalar(oversampling) && oversampling > 0 && oversampling <= 100000) % && (round(oversampling) == oversampling))
    symbolRate = iqparse(get(handles.editSymbolRate, 'String'), 'scalar');
    numSymbols = iqparse(get(handles.editNumSymbols, 'String'), 'scalar');
    [n,d] = rat(oversampling, handles.os_resolution);
    oversampling = n / d;
    sampleRate = symbolRate * oversampling;
    set(handles.editSampleRate, 'String', iqengprintf(sampleRate));
    numSamples = calcNumSamples(numSymbols, oversampling, handles);
    set(handles.editNumSamples, 'String', num2str(numSamples));
    if (d ~= 1)
        set(handles.editOversampling, 'String', sprintf('%d / %d', n, d));
    end
    checkfields([], 0, handles);
end


% --- Executes during object creation, after setting all properties.
function editOversampling_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editOversampling (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


function editNumSymbols_Callback(hObject, eventdata, handles)
% hObject    handle to editNumSymbols (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editNumSymbols as text
%        str2double(get(hObject,'String')) returns contents of editNumSymbols as a double
value = [];
try
    value = iqparse(get(hObject, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
if (isscalar(value) && value >= 2 && value <= 10e6)
    numSymbols = iqparse(get(handles.editNumSymbols, 'String'), 'scalar');
    oversampling = iqparse(get(handles.editOversampling, 'String'), 'scalar');
    [n,d] = rat(oversampling, handles.os_resolution);
    oversampling = n / d;
    numSamples = calcNumSamples(numSymbols, oversampling, handles);
    set(handles.editNumSamples, 'String', num2str(numSamples));
    set(hObject,'BackgroundColor','white');
else
    set(hObject,'BackgroundColor','red');
end


% --- Executes during object creation, after setting all properties.
function editNumSymbols_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editNumSymbols (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


function editNumCarriers_Callback(hObject, eventdata, handles)
% hObject    handle to editNumCarriers (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editNumCarriers as text
%        str2double(get(hObject,'String')) returns contents of editNumCarriers as a double
value = [];
try
    value = iqparse(get(hObject, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
if (isscalar(value) && value >= 1 && value <= 1000)
    set(hObject,'BackgroundColor','white');
else
    set(hObject,'BackgroundColor','red');
end


% --- Executes during object creation, after setting all properties.
function editNumCarriers_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editNumCarriers (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editParam2_Callback(hObject, eventdata, handles)
% hObject    handle to editParam2 (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editParam2 as text
%        str2double(get(hObject,'String')) returns contents of editParam2 as a double


% --- Executes during object creation, after setting all properties.
function editParam2_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editParam2 (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


% --- Executes on selection change in popupmenuModType.
function popupmenuModType_Callback(hObject, eventdata, handles)
% hObject    handle to popupmenuModType (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
modTypeList = get(handles.popupmenuModType, 'String');
modTypeIdx = get(handles.popupmenuModType, 'Value');
modType = modTypeList{modTypeIdx};
switch modType
    case 'QAM256'; resLen = 512; conv = '1e-7';
    case 'QAM512'; resLen = 1024; conv = '1e-8';
    case 'QAM1024'; resLen = 2048; conv = '1e-9';
    case 'QAM2048'; resLen = 4096; conv = '1e-9';
    case 'QAM4096'; resLen = 4096; conv = '1e-9';
    otherwise; resLen = 256; conv = '1e-7';
end
set(handles.editResultLength, 'String', num2str(resLen));
set(handles.editConvergence, 'String', conv);
% % changing the modulation format resets any "custom" modulation
% val = get(handles.pushbuttonPlotConstellation, 'UserData');
% if isa(val, 'iqConstellation') && ~strcmp(val.name, modType)
%     set(handles.pushbuttonPlotConstellation, 'UserData', []);
% end


% --- Executes during object creation, after setting all properties.
function popupmenuModType_CreateFcn(hObject, eventdata, handles)
% hObject    handle to popupmenuModType (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: popupmenu controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editCarrierOffset_Callback(hObject, eventdata, handles)
% hObject    handle to editCarrierOffset (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editCarrierOffset as text
%        str2double(get(hObject,'String')) returns contents of editCarrierOffset as a double
value = [];
try
    value = iqparse(get(hObject, 'String'), 'vector');
catch ex
    msgbox(ex.message);
end
arbConfig = loadArbConfig();
if (isvector(value) && ~isempty(value) ...
        && isempty(find(abs(value) < -1*max(arbConfig.maximumSampleRate))) ...
        && isempty(find(abs(value) > max(arbConfig.maximumSampleRate))))
    if (length(value) > 1)
        set(handles.checkboxMulti, 'Value', 1);
        set(handles.checkboxMulti, 'Enable', 'off');
        set(handles.textMultiCarrier, 'Enable', 'off');
        set(handles.editNumCarriers, 'String', sprintf('%d', length(value)));
        set(handles.pushbuttonMagEqualize, 'Enable', 'on');
    else
        set(handles.checkboxMulti, 'Value', 0);
        set(handles.checkboxMulti, 'Enable', 'on');
        set(handles.textMultiCarrier, 'Enable', 'on');
    end
    if (isfield(arbConfig, 'defaultFc'))
        set(handles.editFc, 'String', iqengprintf(arbConfig.defaultFc + value(1)));
    else
        set(handles.editFc, 'String', iqengprintf(value(1)));
    end
    set(hObject,'BackgroundColor','white');
else
    set(hObject,'BackgroundColor','red');
end
checkboxMulti_Action(hObject, eventdata, handles);


% --- Executes during object creation, after setting all properties.
function editCarrierOffset_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editCarrierOffset (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


% --- Executes on button press in pushbuttonDisplay.
function pushbuttonDisplay_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonDisplay (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
[iqdata sampleRate oversampling marker] = calcModIQ(handles, 'display');
if (~isempty(iqdata))
    %iqplot(iqdata, sampleRate, 'constellation');
    %iqplot(iqdata, sampleRate, 'oversampling', oversampling);
    %iqplot(iqdata, sampleRate, 'marker', marker);
    %iqplot(iqdata, sampleRate, 'CCDF');
    % iqeyeplot(real(iqdata(:,1)), sampleRate, oversampling, 2, 11);
    % iqeyeplot(imag(iqdata(:,1)), sampleRate, oversampling, 2, 12);
    if size(iqdata, 2) > 1
        iqplot(iqdata(:,1), sampleRate, 'subplot', 1);
        iqplot(iqdata(:,2), sampleRate, 'subplot', 2);
        % iqeyeplot(real(iqdata(:,2)), sampleRate, oversampling, 2, 13);
        % iqeyeplot(imag(iqdata(:,2)), sampleRate, oversampling, 2, 14);
    else
        iqplot(iqdata(:,1), sampleRate);
    end
end


% --- Executes on button press in pushbuttonDownload.
function pushbuttonDownload_Callback(hObject, eventdata, handles)
pushbuttonDownload_Action(hObject, eventdata, handles);


%---------------------------------------------------------------------
function pushbuttonDownload_Action(hObject, eventdata, handles)
% hObject    handle to pushbuttonDownload (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
set(hObject, 'Enable', 'off');
handles.lastDownload = 'HW';
guidata(hObject, handles);
[iqdata, sampleRate, ~, marker, channelMapping] = calcModIQ(handles, 'download');
if (~isempty(iqdata))
    segmentNum = iqparse(get(handles.editSegment, 'String'), 'scalar');
    marker = downloadClock(handles);
    iqdata = setFreqInCalToneWindow(handles, iqdata);
    hMsgBox = msgbox('Downloading Waveform. Please wait...', 'Please wait...', 'replace');
%    debugChMap(sprintf('size iqdata: %d %d, chMap', size(iqdata,1), size(iqdata,2)), channelMapping);
    iqdownload(iqdata, sampleRate, 'channelMapping', channelMapping, ...
       'segmentNumber', segmentNum, 'marker', marker);
    try close(hMsgBox); catch; end
end
set(hObject, 'Enable', 'on');
set(handles.pushbuttonCalibrate, 'Enable', 'on');
set(handles.editFc, 'Enable', 'on');
set(handles.textFc, 'Enable', 'on');
set(handles.editFilterLength, 'Enable', 'on');
set(handles.textFilterLength, 'Enable', 'on');
set(handles.editConvergence, 'Enable', 'on');
set(handles.textConvergence, 'Enable', 'on');
set(handles.editResultLength, 'Enable', 'on');
set(handles.textResultLength, 'Enable', 'on');



function iqdata = setFreqInCalToneWindow(handles, iqdata)
% Update the Frequency Edit Field in Calibrated Tone window
try
    amplitude = iqparse(get(handles.editMagnitudes, 'String'), 'vector');
    freq = iqparse(get(handles.editCarrierOffset, 'String'), 'vector');
    if (~isreal(amplitude) || ~isscalar(amplitude) || ~isreal(freq) || ~isscalar(freq))
        return
    end
    % figure out the crest factor of the signal and adjust the power level
    % accordingly
    rms = norm(real(iqdata(:,1))) ./ sqrt(length(iqdata(:,1)));
    peak = max(abs(real(iqdata(:,1))));
    crestdB = 10*log10(peak^2/rms^2);
    amplitude = amplitude + crestdB;
    TempHide = get(0, 'ShowHiddenHandles');
    set(0, 'ShowHiddenHandles', 'on');
    figs = findobj(0, 'Type', 'figure', 'Name', 'Tones with calibrated power level');
    set(0, 'ShowHiddenHandles', TempHide);
    for i = 1:length(figs)
        fig = figs(i);
        [path file ext] = fileparts(get(fig, 'Filename'));
        xhandles = guihandles(fig);
        set(xhandles.editFreq, 'String', iqengprintf(freq));
        set(xhandles.editPower, 'String', iqengprintf(amplitude));
        feval(file, 'editFreq_Action', xhandles.editFreq, 'check', xhandles);
        feval(file, 'editPower_Action', xhandles.editPower, 'check', xhandles);
        chMap = get(handles.pushbuttonChannelMapping, 'UserData');
        ed = cell2struct({'setFreq', chMap, freq, amplitude}, ...
                         {'cmd', 'channelMapping', 'freq', 'power'}, 2);
        result = feval(file, 'setFreqAndPower', xhandles, ed);
        if (~isempty(result))
            scale = max(max(abs(real(iqdata(:,1)))), max(abs(imag(iqdata(:,1)))));
            iqdata = iqdata / scale;
        end
    end
catch ex
    errordlg({ex.message, [ex.stack(1).name ', line ' num2str(ex.stack(1).line)]});
end


function [div,clockPat] = getDivClock(handles)
% determine the state of the "Clock" menu selection
% returns div=1 / clockPat='clock' if no clock option is selected
div = 1;
clockPat = 'clock';
if (strcmp('on', get(handles.menuClock2, 'Checked')))
    div = 2;
    clockPat = 'clock';
elseif (strcmp('on', get(handles.menuClock3, 'Checked')))
    div = 3;
    clockPat = 'clock3';
elseif (strcmp('on', get(handles.menuClock4, 'Checked')))
    div = 4;
    clockPat = 'clock4';
elseif (strcmp('on', get(handles.menuClock5, 'Checked')))
    div = 5;
    clockPat = 'clock5';
elseif (strcmp('on', get(handles.menuClock6, 'Checked')))
    div = 6;
    clockPat = 'clock6';
elseif (strcmp('on', get(handles.menuClock7, 'Checked')))
    div = 7;
    clockPat = 'clock7';
elseif (strcmp('on', get(handles.menuClock8, 'Checked')))
    div = 8;
    clockPat = 'clock8';
elseif (strcmp('on', get(handles.menuClock16, 'Checked')))
    div = 16;
    clockPat = 'clock16';
elseif (strcmp('on', get(handles.menuClockOnce, 'Checked')))
    clockPat = 'clockOnce';
end


function marker = downloadClock(handles)
% download a clock signal on unchecked channels, but don't start the generator
marker = [];
[div,clockPat] = getDivClock(handles);
numSymbols = iqparse(get(handles.editNumSymbols, 'String'), 'scalar');
% check if we need to generate a clock at all
if (div > 1)
    if (mod(numSymbols, div) ~= 0)
        warndlg(sprintf('Number of bits is not a multiple of %d - clock signal will not be periodic', div), 'Warning', 'replace');
    end
    % calculate the clock waveform
    [s fs oversampling marker chMap] = calcModIQ(handles, 'clock', 0, clockPat);
    if (~isempty(s))
        segmentNum = iqparse(get(handles.editSegment, 'String'), 'scalar');
        if (~isempty(find(chMap(1:end), 1)))
            hMsgBox = msgbox('Downloading Clock Signal. Please wait...', 'Please wait...', 'replace');
            iqdownload(s, fs, 'channelMapping', chMap, 'segmentNumber', segmentNum, 'run', 0);
            try close(hMsgBox); catch ex; end
        end
        % calculate the marker signal
        symbolRate = iqparse(get(handles.editSymbolRate, 'String'), 'scalar');
        numSamples = length(s);
        % find the oversampling ratio, ignore the fractional part, since it
        % can not be realized with markers
        [overN overD] = rat(fs / symbolRate * div);
        % for 1x oversampling, set marker every other symbol
        overN = max(overN, 2);
        % don't send markers faster than 10 GHz (DCA)
        maxTrig = 5e9;
        % for M8190A, max toggle rate for markers = sequencer clock
        if (fs <= 12e9) 
            maxTrig = fs / 64;
        end
        % for M8195A, markers can toggle at a max. rate of fs/128
        if (fs > 50e9 && fs < 70e9)
            maxTrig = fs / 128;
        end
        if (ceil(fs / maxTrig / overN) > 1)
            overN = overN * ceil(fs / maxTrig / overN);
        end
        h1 = floor(overN / 2);
        h2 = overN - h1;
        marker = repmat([15*ones(1,h1) zeros(1,h2)], 1, ceil(numSamples / overN));
        marker = marker(1:numSamples);
    end
end


% --- Executes on button press in pushbuttonShowCorrection.
function pushbuttonShowCorrection_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonShowCorrection (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
iqcorrmgmt();


function editCarrierSpacing_Callback(hObject, eventdata, handles)
% hObject    handle to editCarrierSpacing (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editCarrierSpacing as text
%        str2double(get(hObject,'String')) returns contents of editCarrierSpacing as a double
checkCarrierSpacingSymbolRate(handles);


function checkCarrierSpacingSymbolRate(handles)
carrierSpacing = [];
csValid = false;
symbolRate = [];
srValid = false;
ofValid = false;
offset = 0;
numCarrier = 1;
arbConfig = loadArbConfig();
try
    carrierSpacing = iqparse(get(handles.editCarrierSpacing, 'String'), 'scalar');
catch ex
end
try
    symbolRate = iqparse(get(handles.editSymbolRate, 'String'), 'scalar');
catch ex
end
try
    offset = iqparse(get(handles.editCarrierOffset, 'String'), 'vector');
catch ex
end
try
    numCarrier = iqparse(get(handles.editNumCarriers, 'String'), 'scalar');
catch ex
end
multi = get(handles.checkboxMulti, 'Value');

if (isscalar(carrierSpacing) && carrierSpacing >= 0 && carrierSpacing <= max(arbConfig.maximumSampleRate))
    csValid = true;
end
if (isscalar(symbolRate) && symbolRate <= max(arbConfig.maximumSampleRate))
    srValid = true;
end
if (isvector(offset) && ~isempty(offset) ...
        && isempty(find(abs(offset) > max(arbConfig.maximumSampleRate))))
    ofValid = true;
end
if (csValid && srValid && length(offset) > 1 && symbolRate > min(diff(sort(offset))))
    ofValid = false;
    srValid = false;
end
if (csValid && srValid && length(offset) <= 1 && multi && carrierSpacing < symbolRate)
    csValid = false;
    srValid = false;
end
if (csValid)
    set(handles.editCarrierSpacing,'BackgroundColor','white');
else
    set(handles.editCarrierSpacing,'BackgroundColor','red');
end
if (srValid)
    set(handles.editSymbolRate,'BackgroundColor','white');
else
    set(handles.editSymbolRate,'BackgroundColor','red');
end
if (ofValid)
    set(handles.editCarrierOffset,'BackgroundColor','white');
else
    set(handles.editCarrierOffset,'BackgroundColor','red');
end


% --- Executes during object creation, after setting all properties.
function editCarrierSpacing_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editCarrierSpacing (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


% --- Executes on button press in checkboxAutoSamples.
function checkboxAutoSamples_Callback(hObject, eventdata, handles)
% hObject    handle to checkboxAutoSamples (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hint: get(hObject,'Value') returns toggle state of checkboxAutoSamples
autoSamples = get(hObject,'Value');
if (autoSamples)
    set(handles.editNumSamples, 'Enable', 'off');
else
    set(handles.editNumSamples, 'Enable', 'on');
end


% --- Executes on selection change in popupmenuFilter.
function popupmenuFilter_Callback(hObject, eventdata, handles)
% hObject    handle to popupmenuFilter (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: contents = cellstr(get(hObject,'String')) returns popupmenuFilter contents as cell array
%        contents{get(hObject,'Value')} returns selected item from popupmenuFilter
filterList = get(handles.popupmenuFilter, 'String');
filter = filterList{get(handles.popupmenuFilter, 'Value')};
if (strcmp(filter, 'Gaussian'))
    set(handles.textNSymAlpha, 'String', '        Nsym / BT');
else
    set(handles.textNSymAlpha, 'String', '        Nsym / Alpha');
end
editFilterBeta_Action(hObject, eventdata, handles);


% --- Executes during object creation, after setting all properties.
function popupmenuFilter_CreateFcn(hObject, eventdata, handles)
% hObject    handle to popupmenuFilter (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: popupmenu controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


function editSymbolRate_Callback(hObject, eventdata, handles)
editSymbolRate_Action(hObject, eventdata, handles);


%---------------------------------------------------------------------
function editSymbolRate_Action(hObject, eventdata, handles)
% hObject    handle to editSymbolRate (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editSymbolRate as text
%        str2double(get(hObject,'String')) returns contents of editSymbolRate as a double
arbConfig = loadArbConfig();
symbolRate = [];
try
    symbolRate = iqparse(get(handles.editSymbolRate, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
if (isscalar(symbolRate) && symbolRate >= 1e3 && symbolRate <= arbConfig.maximumSampleRate(1))
    oldSampleRate = iqparse(get(handles.editSampleRate, 'String'), 'scalar');
    numSymbols = iqparse(get(handles.editNumSymbols, 'String'), 'scalar');
    sampleRate = oldSampleRate;
    % re-calculate oversampling & sampleRate - try to make it integer
%     oversampling = floor(oldSampleRate / symbolRate);
%     if (oversampling < 1)
%         oversampling = 1;
%     end
%     sampleRate = symbolRate * oversampling;
%     if (sampleRate < min(arbConfig.minimumSampleRate))
%         % if sample rate is too small, try non-integer oversampling
%         sampleRate = oldSampleRate;
% %        sampleRate = arbConfig.defaultSampleRate;
% %        set(handles.editSampleRate, 'String', iqengprintf(sampleRate));
%     end
    [n,d] = rat(sampleRate / symbolRate, handles.os_resolution);
    oversampling = n/d;
    if (d ~= 1)
        set(handles.editOversampling, 'String', sprintf('%d / %d', n, d));
    else
        set(handles.editOversampling, 'String', num2str(oversampling));
    end
    set(handles.editSampleRate, 'String', iqengprintf(sampleRate));
    numSamples = calcNumSamples(numSymbols, oversampling, handles);
    set(handles.editNumSamples, 'String', num2str(numSamples));
end
checkfields(hObject, 0, handles);


% --- Executes during object creation, after setting all properties.
function editSymbolRate_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editSymbolRate (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editMagnitudes_Callback(hObject, eventdata, handles)
% hObject    handle to editMagnitudes (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editMagnitudes as text
%        str2double(get(hObject,'String')) returns contents of editMagnitudes as a double
value = [];
try
    value = iqparse(get(hObject, 'String'), 'vector');
catch ex
    msgbox(ex.message);
end
if (isvector(value) && length(value) >= 1)
    set(hObject,'BackgroundColor','white');
else
    set(hObject,'BackgroundColor','red');
end


% --- Executes during object creation, after setting all properties.
function editMagnitudes_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editMagnitudes (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


% --- Executes on button press in checkboxCorrection.
function checkboxCorrection_Callback(hObject, eventdata, handles)
checkboxCorrection_Action(hObject, eventdata, handles);


%---------------------------------------------------------------------
function checkboxCorrection_Action(hObject, eventdata, handles)
% hObject    handle to checkboxCorrection (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hint: get(hObject,'Value') returns toggle state of checkboxCorrection
correction = get(handles.checkboxCorrection,'Value');
if (correction)
    set(handles.pushbuttonCalibrate, 'String', 'Re-calibrate');
else
    set(handles.pushbuttonCalibrate, 'String', 'Calibrate (VSA)');
end;




function editFilterNsym_Callback(hObject, eventdata, handles)
% hObject    handle to editFilterNsym (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editFilterNsym as text
%        str2double(get(hObject,'String')) returns contents of editFilterNsym as a double
value = [];
try
    value = iqparse(get(hObject, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
if (isscalar(value) && value >= 1 && value <= 5000)
    set(hObject,'BackgroundColor','white');
else
    set(hObject,'BackgroundColor','red');
end


% --- Executes during object creation, after setting all properties.
function editFilterNsym_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editFilterNsym (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editFilterBeta_Callback(hObject, eventdata, handles)
editFilterBeta_Action(hObject, eventdata, handles);


%---------------------------------------------------------------------
function editFilterBeta_Action(hObject, eventdata, handles)
% hObject    handle to editFilterBeta (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editFilterBeta as text
%        str2double(get(hObject,'String')) returns contents of editFilterBeta as a double
value = [];
try
    value = iqparse(get(handles.editFilterBeta, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
filterList = get(handles.popupmenuFilter, 'String');
filterIdx = get(handles.popupmenuFilter, 'Value');
filterType = filterList{filterIdx};
if (isscalar(value) && value >= 0 && (value <= 1 || isempty(strfind(filterType, 'osine'))))
    set(handles.editFilterBeta, 'BackgroundColor', 'white');
else
    set(handles.editFilterBeta, 'BackgroundColor', 'red');
end


% --- Executes during object creation, after setting all properties.
function editFilterBeta_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editFilterBeta (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


% --- Executes on button press in checkboxMulti.
function checkboxMulti_Callback(hObject, eventdata, handles)
checkboxMulti_Action(hObject, eventdata, handles);


%---------------------------------------------------------------------
function checkboxMulti_Action(hObject, eventdata, handles)
% hObject    handle to checkboxMulti (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hint: get(hObject,'Value') returns toggle state of checkboxMulti
multiCarrier = get(handles.checkboxMulti,'Value');
offset = iqparse(get(handles.editCarrierOffset, 'String'), 'vector');
if (multiCarrier)
    if (length(offset) > 1)
        set(handles.editNumCarriers, 'Enable', 'off');
        set(handles.editCarrierSpacing, 'Enable', 'off');
    else
        set(handles.editNumCarriers, 'Enable', 'on');
        set(handles.editCarrierSpacing, 'Enable', 'on');
    end
    set(handles.editMagnitudes, 'Enable', 'on');
    set(handles.pushbuttonMagEqualize, 'Enable', 'on');
    set(handles.multiCarrierControl, 'Enable', 'on');
else
    set(handles.editNumCarriers, 'Enable', 'off');
    set(handles.editCarrierSpacing, 'Enable', 'off');
    set(handles.editMagnitudes, 'Enable', 'off');
    set(handles.pushbuttonMagEqualize, 'Enable', 'off');
    set(handles.multiCarrierControl, 'Enable', 'off');
end;
checkCarrierSpacingSymbolRate(handles);



function editFc_Callback(hObject, eventdata, handles)
% hObject    handle to editFc (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editFc as text
%        str2double(get(hObject,'String')) returns contents of editFc as a double
value = [];
try
    value = iqparse(get(hObject, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
% allow positive and negative Fc, negative ones indicate that
% the spectrum is inverted
if (isscalar(value) && isfloat(value))
    set(hObject,'BackgroundColor','white');
else
    set(hObject,'BackgroundColor','red');
end


% --- Executes during object creation, after setting all properties.
function editFc_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editFc (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end

function editFilterLength_Callback(hObject, eventdata, handles)
% hObject    handle to editFilterLength (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editFilterLength as text
%        str2double(get(hObject,'String')) returns contents of editFilterLength as a double
value = [];
try
    value = iqparse(get(hObject, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
if (isscalar(value) && value >= 1 && value <= 99 && (round(value) == value))
    set(hObject,'BackgroundColor','white');
else
    set(hObject,'BackgroundColor','red');
end


% --- Executes during object creation, after setting all properties.
function editFilterLength_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editFilterLength (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editResultLength_Callback(hObject, eventdata, handles)
% hObject    handle to editResultLength (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editResultLength as text
%        str2double(get(hObject,'String')) returns contents of editResultLength as a double
value = [];
try
    value = iqparse(get(hObject, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
if (isscalar(value) && value >= 1 && value <= 10000 && (round(value) == value))
    set(hObject,'BackgroundColor','white');
else
    set(hObject,'BackgroundColor','red');
end


% --- Executes during object creation, after setting all properties.
function editResultLength_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editResultLength (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editConvergence_Callback(hObject, eventdata, handles)
% hObject    handle to editConvergence (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editConvergence as text
%        str2double(get(hObject,'String')) returns contents of editConvergence as a double
value = [];
try
    value = iqparse(get(hObject, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
if (isscalar(value) && value > 0 && value <= 1)
    set(hObject,'BackgroundColor','white');
else
    set(hObject,'BackgroundColor','red');
end



function editSegment_Callback(hObject, eventdata, handles)
% hObject    handle to editSegment (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editSegment as text
%        str2double(get(hObject,'String')) returns contents of editSegment as a double
checkfields(hObject, 0, handles);

% --- Executes during object creation, after setting all properties.
function editSegment_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editSegment (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


% --- Executes during object creation, after setting all properties.
function editConvergence_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editConvergence (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


% --- Executes on button press in pushbuttonShowVSA.
function pushbuttonShowVSA_Callback(hObject, eventdata, handles)
pushbuttonShowVSA_Action(hObject, eventdata, handles);


%---------------------------------------------------------------------
function pushbuttonShowVSA_Action(hObject, eventdata, handles)
% hObject    handle to pushbuttonShowVSA (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
showInVSA(hObject, handles, 1);



function showInVSA(hObject, handles, doSetup)
handles.lastDownload = 'VSA';
guidata(hObject, handles);
fc = iqparse(get(handles.editCarrierOffset, 'String'), 'vector');
fc = fc(1);
symbolRate = iqparse(get(handles.editSymbolRate, 'String'), 'scalar');
modTypeList = get(handles.popupmenuModType, 'String');
modType = modTypeList{get(handles.popupmenuModType, 'Value')};
iqCnst = get(handles.pushbuttonPlotConstellation, 'UserData');
if ~isempty(iqCnst) && isa(iqCnst, 'iqConstellation') && strcmp(modType, iqCnst.name)
    modType = iqCnst;
end
filterList = get(handles.popupmenuFilter, 'String');
filterIdx = get(handles.popupmenuFilter, 'Value');
filterBeta = iqparse(get(handles.editFilterBeta, 'String'), 'scalar');
resultLength = iqparse(get(handles.editResultLength, 'String'), 'scalar');
filterLength = iqparse(get(handles.editFilterLength, 'String'), 'scalar');
convergence = iqparse(get(handles.editConvergence, 'String'), 'scalar');
dataTypeList = get(handles.popupmenuData, 'String');
dataType = dataTypeList{get(handles.popupmenuData, 'Value')};
if contains(dataType, 'PRBS')
    if strcmp(dataType, 'Std. PRBS')
        prbsList = get(handles.popupmenuPrbs, 'String');
        dataType = ['PRBS ' strrep(lower(prbsList{get(handles.popupmenuPrbs, 'Value')}), ' ', '')];
    elseif strcmp(dataType, 'Custom PRBS')
        dataType = ['PRBS ' get(handles.editCustomPrbs, 'String')];
    end
    if get(handles.checkboxPrbsDC, 'Value')
        dataType = [dataType ' (DC balanced)'];
    end
end

[iqdata, sampleRate, ~, ~, ~] = calcModIQ(handles, 'none');
if (isempty(iqdata))
    warndlg('For large waveforms, VSA visualization is not available. Please reduce the number of symbols');
    return;
end
vsaApp = vsafunc([], 'open');
if (~isempty(vsaApp))
    hMsgBox = msgbox('Configuring VSA software. Please wait...');
    if (doSetup)
        vsafunc(vsaApp, 'preset');
        assert(size(iqdata,2) <= 2, 'expected no more than 2 columns');
        vsafunc(vsaApp, 'input', 1, size(iqdata, 2));
    end
    vsafunc(vsaApp, 'load', iqdata, sampleRate);
    if (doSetup)
        demodType = 'CustomIQ'; % 'DigDemod';
        vsafunc(vsaApp, demodType, modType, symbolRate, filterList{filterIdx}, filterBeta, resultLength, dataType);
        vsafunc(vsaApp, 'equalizer', false, filterLength, convergence, demodType);
        if (strcmp(filterList{filterIdx}, 'Gaussian'))
            spanScale = 9 * filterBeta;
        else
            spanScale = 1 + filterBeta;
        end
        vsafunc(vsaApp, 'freq', fc, symbolRate * spanScale, 51201, 'flattop', 3);
        dualPol = strcmp('on', get(handles.menuDualPolarization, 'Checked'));
        vsafunc(vsaApp, 'trace', 4 + 2*dualPol, demodType, size(iqdata,2));
        vsafunc(vsaApp, 'start', 1);
        vsafunc(vsaApp, 'autoscale');
    end
    try
        close(hMsgBox);
    catch
    end
end


% --- Executes on button press in pushbuttonSetupVSA.
function pushbuttonSetupVSA_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonSetupVSA (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
% --- Executes on button press in pushbuttonCalibrate.
downloadAndSetupVSA(hObject, eventdata, handles, 0);


function pushbuttonCalibrate_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonCalibrate (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
downloadAndSetupVSA(hObject, eventdata, handles, 1);


function downloadAndSetupVSA(hObject, eventdata, handles, doCal)
symbolRate = iqparse(get(handles.editSymbolRate, 'String'), 'scalar');
modTypeList = get(handles.popupmenuModType, 'String');
modTypeIdx = get(handles.popupmenuModType, 'Value');
modType = modTypeList{modTypeIdx};
iqCnst = get(handles.pushbuttonPlotConstellation, 'UserData');
if ~isempty(iqCnst) && isa(iqCnst, 'iqConstellation') && strcmp(modType, iqCnst.name)
    modType = iqCnst;
end
filterList = get(handles.popupmenuFilter, 'String');
filterIdx = get(handles.popupmenuFilter, 'Value');
filterBeta = iqparse(get(handles.editFilterBeta, 'String'), 'scalar');
numCarriers = iqparse(get(handles.editNumCarriers, 'String'), 'scalar');
carrierSpacing = iqparse(get(handles.editCarrierSpacing, 'String'), 'scalar');
carrierOffset = iqparse(get(handles.editCarrierOffset, 'String'), 'vector');
fc = iqparse(get(handles.editFc, 'String'), 'scalar');
filterLength = iqparse(get(handles.editFilterLength, 'String'), 'scalar');
convergence = iqparse(get(handles.editConvergence, 'String'), 'scalar');
resultLength = iqparse(get(handles.editResultLength, 'String'), 'scalar');
multiCarrier = get(handles.checkboxMulti, 'Value');
recal = get(handles.checkboxCorrection, 'Value');
oldAdjustment = iqparse(get(handles.editMagnitudes, 'String'), 'vector');
dataTypeList = get(handles.popupmenuData, 'String');
dataType = dataTypeList{get(handles.popupmenuData, 'Value')};
if contains(dataType, 'PRBS')
    if strcmp(dataType, 'Std. PRBS')
        prbsList = get(handles.popupmenuPrbs, 'String');
        dataType = ['PRBS ' strrep(lower(prbsList{get(handles.popupmenuPrbs, 'Value')}), ' ', '')];
    elseif strcmp(dataType, 'Custom PRBS')
        dataType = ['PRBS ' get(handles.editCustomPrbs, 'String')];
    end
    if get(handles.checkboxPrbsDC, 'Value')
        dataType = [dataType ' (DC balanced)'];
    end
end

useHW = (isfield(handles, 'lastDownload') && strcmp(handles.lastDownload, 'HW') || ~doCal);
if (~recal && doCal)
    [ampCorr perChannelCorr] = iqcorrection([]);
    if (~isempty(perChannelCorr))
        res = questdlg({'You have per-channel corrections defined, but they are not applied.' ...
            'Do you want to continue?? ' ...
            '(If you click "Yes", the per-channel corrections will be erased)'}, ...
            'Calibration', 'Yes', 'No', 'No');
        if (strcmp(res, 'Yes') == 0)
            return;
        end
    end
end
ampCorr = [];

%% if multicarrier
if (multiCarrier && doCal)
    if (length(carrierOffset) == 1 && numCarriers > 1)
        carrierOffset = carrierOffset:carrierSpacing:(carrierOffset + (numCarriers - 1) * carrierSpacing);
    else
        carrierOffset = sort(carrierOffset);
    end
    
    % save some app data for the multical process
    setappdata(0,'symRate', symbolRate);
    setappdata(0,'modTypeList', modTypeList);
    setappdata(0,'modTypeIdx', modTypeIdx);
    setappdata(0,'filterList', filterList);
    setappdata(0,'filterIdx', filterIdx);
    setappdata(0,'filterBeta', filterBeta);
    setappdata(0,'numOfCarriers', numCarriers);
    setappdata(0,'carrierSpacing', carrierSpacing);
    setappdata(0,'carrierOffsetText', get(handles.editCarrierOffset, 'String') );
    setappdata(0,'vsaFc', fc);
    setappdata(0,'vsaFilterLength', filterLength);
    setappdata(0,'vsaConvergence', convergence);
    setappdata(0,'vsaResultLength', resultLength);
    setappdata(0, 'chCenterFreq', plus(carrierOffset, fc));
    setappdata(0, 'chBand', (symbolRate * (1+ filterBeta)));
    
    % remove previous corrections
    set(handles.checkboxCorrection, 'Value', 0);
    
    doLastDownload(hObject, eventdata, handles);
    
    % Open the multi-carrier cal gui
    ccParams = multiCalDialog_GUI;
    %waitfor(ccParams);
    if ccParams == -1
        return
    end
    
    multiCalParams = getappdata(0,'multiCalParameters');
    chPowerCorrection = getappdata(0,'chPowerCorrection');
    
    % if requested update the relative powers of the signal and download
    % the waveform again.
    if chPowerCorrection
        powers= cell2mat(multiCalParams(:,4));
        minPower = min(powers);
        relativeMags = '';
        
        % Make sure our array is the right size, fill with zeros to num carriers
        if length(oldAdjustment) < numCarriers
            oldAdjustment(numCarriers) = 0;
        end
        
        for i= 1:size(multiCalParams,1)
            adjustment = num2str((oldAdjustment(i) + (minPower - powers(i))), '%2.3f');
            relativeMags = strcat(relativeMags, adjustment,',');
        end
        % delete last comma
        relativeMags = relativeMags(1:end-1);
        set(handles.editMagnitudes, 'String', relativeMags);
        
        % download data again
        doLastDownload(hObject, eventdata, handles);
        chPowerCorrection = false;
    end
    
    for i = 1:length(carrierOffset)
        fc = cell2mat(multiCalParams(i,2));
        range = cell2mat(multiCalParams(i,5));
        mixerMode = char(multiCalParams(i,6));
        customFilterFile = char(multiCalParams(i,7));
        
        result = iqvsamultical('symbolRate', symbolRate, ...
            'modType', modType, ...
            'filterType', filterList{filterIdx}, ...
            'filterBeta', filterBeta, ...
            'carrierOffset', carrierOffset(i), ...
            'fc', fc , ...
            'filterLength', filterLength, ...
            'convergence', convergence, ...
            'resultLength', resultLength, ...
            'recalibrate', recal, ...
            'useHW', useHW, ...
            'doCal', doCal, ...
            'mixerMode', mixerMode, ...
            'customFilterFile', customFilterFile, ...
            'range', range, ...
            'demodType', 'CustomIQ');
        if (result ~= 0)
            return;
        end
        [corr, ~] = iqcorrection([]);
        % --- merge correction data
        if (isempty(ampCorr))
            ampCorr = corr;
        else
            % boundary is in the middle of the carriers
            df = (carrierOffset(i) + carrierOffset(i-1)) / 2;
            i1 = find(ampCorr(:,1) <= df);
            i2 = find(corr(:,1) > df);
            ampCorr = [ampCorr(i1,:); corr(i2,:)];
            % write the cal file
            save(iqampCorrFilename(), 'ampCorr');
            % plot the merged freq response
            figure(10);
            set(10, 'Name', 'Correction');
            subplot(2,1,1);
            plot(ampCorr(:,1), -20*log10(abs(ampCorr(:,3:end))), '.-');
            xlabel('Frequency (Hz)');
            ylabel('dB');
            grid on;
            subplot(2,1,2);
            plot(ampCorr(:,1), -180/pi*unwrap(angle(ampCorr(:,3:end))), 'm.-');
            xlabel('Frequency (Hz)');
            ylabel('degree');
            grid on;
        end
    end
    
else
    %% single Carrier take parameters from iqmod_gui
    
    doLastDownload(hObject, eventdata, handles);
    dualPol = strcmp('on', get(handles.menuDualPolarization, 'Checked'));
    
    for i = 1:length(carrierOffset)
        result = iqvsacal('symbolRate', symbolRate, ...
            'modType', modType, ...
            'filterType', filterList{filterIdx}, ...
            'filterBeta', filterBeta, ...
            'carrierOffset', carrierOffset(i), ...
            'fc', fc + carrierOffset(i) - carrierOffset(1), ...
            'filterLength', filterLength, ...
            'convergence', convergence, ...
            'resultLength', resultLength, ...
            'recalibrate', recal, ...
            'useHW', useHW, ...
            'doCal', doCal, ...
            'demodType', 'CustomIQ', ...
            'dualPol', dualPol, ...
            'dataType', dataType);
        if (result ~= 0)
            return;
        end
        [corr, ~] = iqcorrection([]);
        % --- merge correction data
        if (isempty(ampCorr))
            ampCorr = corr;
        else
            % boundary is in the middle of the carriers
            df = (carrierOffset(i) + carrierOffset(i-1)) / 2;
            i1 = find(ampCorr(:,1) <= df);
            i2 = find(corr(:,1) > df);
            ampCorr = [ampCorr(i1,:); corr(i2,:)];
            % write the cal file
            save(iqampCorrFilename(), 'ampCorr');
            % plot the merged freq response
            figure(10);
            set(10, 'Name', 'Correction');
            subplot(2,1,1);
            plot(ampCorr(:,1), -20*log10(abs(ampCorr(:,3:end))), '.-');
            xlabel('Frequency (Hz)');
            ylabel('dB');
            grid on;
            subplot(2,1,2);
            plot(ampCorr(:,1), -180/pi*unwrap(angle(ampCorr(:,3:end))), 'm.-');
            xlabel('Frequency (Hz)');
            ylabel('degree');
            grid on;
        end
    end
end

% if the calibration was successful, download the corrected signal
if (result == 0 && doCal)
    set(handles.checkboxCorrection, 'Value', 1);
    checkboxCorrection_Action(hObject, eventdata, handles);
    if (isfield(handles, 'lastDownload') && strcmp(handles.lastDownload, 'DCA'))
        pushbuttonDownload_Action(hObject, eventdata, handles);
        menuDCAVSA_Action(hObject, eventdata, handles);
    elseif (isfield(handles, 'lastDownload') && strcmp(handles.lastDownload, 'M8135A'))
        pushbuttonDownload_Action(hObject, eventdata, handles);
        menuUSPAVSA_Action(hObject, eventdata, handles);
    else
        doLastDownload(hObject, eventdata, handles);
    end
    try
        close(10);
    catch
    end
    updateCorrWindow();
end


function doLastDownload(hObject, eventdata, handles)
% perform the "last" download action: either download to HW or to VSA
if (isfield(handles, 'lastDownload') && strcmp(handles.lastDownload, 'VSA'))
    pushbuttonShowVSA_Action(hObject, eventdata, handles);
elseif (isfield(handles, 'lastDownload') && strcmp(handles.lastDownload, 'HW'))
    pushbuttonDownload_Action(hObject, eventdata, handles);
elseif (isfield(handles, 'lastDownload') && (strcmp(handles.lastDownload, 'DCA') || strcmp(handles.lastDownload, 'M8135A')))
%    fprintf('already loaded\n');
end


function updateCorrWindow()
% If Correction Mgmt Window is open, refresh it
try
    TempHide = get(0, 'ShowHiddenHandles');
    set(0, 'ShowHiddenHandles', 'on');
    figs = findobj(0, 'Type', 'figure', 'Name', 'Correction Management');
    set(0, 'ShowHiddenHandles', TempHide);
    if (~isempty(figs))
        iqcorrmgmt();
    end
catch ex
end


% --------------------------------------------------------------------
function menuPreset_Callback(hObject, eventdata, handles)
% hObject    handle to menuPreset (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)


% --------------------------------------------------------------------
function menu_QAM16_1GSym_Callback(hObject, eventdata, handles)
% hObject    handle to menu_QAM16_1GSym (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
arbConfig = loadArbConfig();
symbolRate = 1e9;
overSampling = floor(arbConfig.defaultSampleRate / symbolRate);
sampleRate = symbolRate * overSampling;
if (overSampling < 1)
    errordlg('symbol rate too high for this instrument');
    return;
end
set(handles.editSymbolRate, 'String', iqengprintf(symbolRate));
set(handles.editOversampling, 'String', iqengprintf(overSampling));
set(handles.editSampleRate, 'String', iqengprintf(sampleRate));
set(handles.popupmenuModType, 'Value', 8);  % QAM16
set(handles.popupmenuFilter, 'Value', 1); % RRC
set(handles.editFilterNsym, 'String', '20');
set(handles.editFilterBeta, 'String', '0.35');
set(handles.editCarrierOffset, 'String', '2e9');
set(handles.editFc, 'String', '2e9');
set(handles.checkboxMulti, 'Value', 0);
editSymbolRate_Action(hObject, eventdata, handles);
checkboxMulti_Action(hObject, eventdata, handles);


% --------------------------------------------------------------------
function menu_QAM16_1_76GSym_Callback(hObject, eventdata, handles)
% hObject    handle to menu_QAM16_1_76GSym (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
arbConfig = loadArbConfig();
symbolRate = 1.76e9;
overSampling = floor(arbConfig.defaultSampleRate / symbolRate);
sampleRate = symbolRate * overSampling;
if (overSampling < 1)
    errordlg('symbol rate too high for this instrument');
    return;
end
fc = 2e9;
set(handles.editSymbolRate, 'String', iqengprintf(symbolRate));
set(handles.editOversampling, 'String', iqengprintf(overSampling));
set(handles.editSampleRate, 'String', iqengprintf(sampleRate));
set(handles.popupmenuModType, 'Value', 8);  % QAM16
set(handles.popupmenuFilter, 'Value', 1); % RRC
set(handles.editFilterNsym, 'String', '20');
set(handles.editFilterBeta, 'String', '0.35');
set(handles.editCarrierOffset, 'String', iqengprintf(fc));
set(handles.editFc, 'String', iqengprintf(fc + arbConfig.defaultFc));
set(handles.checkboxMulti, 'Value', 0);
editSymbolRate_Action(hObject, eventdata, handles);
checkboxMulti_Action(hObject, eventdata, handles);


% --------------------------------------------------------------------
function MultiCarrier_Callback(hObject, eventdata, handles)
% hObject    handle to MultiCarrier (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
arbConfig = loadArbConfig();
symbolRate = 6e6;
carrierSpacing = 8e6;
overSampling = floor(max(arbConfig.maximumSampleRate) / symbolRate);
sampleRate = symbolRate * overSampling;
if (overSampling < 1)
    errordlg('symbol rate too high for this instrument');
    return;
end
fc = 100e6;
set(handles.editSymbolRate, 'String', iqengprintf(symbolRate));
set(handles.editOversampling, 'String', iqengprintf(overSampling));
set(handles.editSampleRate, 'String', iqengprintf(sampleRate));
set(handles.editNumSymbols, 'String', iqengprintf(192));
set(handles.popupmenuModType, 'Value', 8);  % QAM16
set(handles.popupmenuFilter, 'Value', 1); % RRC
set(handles.editFilterNsym, 'String', '20');
set(handles.editFilterBeta, 'String', '0.35');
set(handles.editCarrierOffset, 'String', iqengprintf(fc));
set(handles.editFc, 'String', iqengprintf(fc + arbConfig.defaultFc));
set(handles.checkboxMulti, 'Value', 1);
set(handles.editCarrierSpacing, 'String', iqengprintf(carrierSpacing));
set(handles.editNumCarriers, 'String', '50');
set(handles.editMagnitudes, 'String', '0 0 0 0 0 -300');
editSymbolRate_Action(hObject, eventdata, handles);
checkboxMulti_Action(hObject, eventdata, handles);



function [iqdata sampleRate oversampling marker channelMapping] = calcModIQ(handles, fct, doCode, clockPat)
% handles    structure with handles and user data (see GUIDATA)
marker = [];
dualPol = strcmp('on', get(handles.menuDualPolarization, 'Checked'));
sampleRate = iqparse(get(handles.editSampleRate, 'String'), 'scalar');
% autoSamples = get(handles.checkboxAutoSamples, 'Value');
numSymbols = iqparse(get(handles.editNumSymbols, 'String'), 'scalar');
modTypeList = get(handles.popupmenuModType, 'String');
modType = modTypeList{get(handles.popupmenuModType, 'Value')};
iqCnst = get(handles.pushbuttonPlotConstellation, 'UserData');
if ~isempty(iqCnst) && isa(iqCnst, 'iqConstellation') && strcmp(modType, iqCnst.name)
    modType = iqCnst;
end
dataTypeList = get(handles.popupmenuData, 'String');
dataType = dataTypeList{get(handles.popupmenuData, 'Value')};
filename = get(handles.editFilename, 'String');
dataContent = iqparse(get(handles.editData, 'String'), 'vector');
oversampling = iqparse(get(handles.editOversampling, 'String'), 'scalar');
filterList = get(handles.popupmenuFilter, 'String');
filterIdx = get(handles.popupmenuFilter, 'Value');
filterNsym = iqparse(get(handles.editFilterNsym, 'String'), 'scalar');
filterBeta = iqparse(get(handles.editFilterBeta, 'String'), 'scalar');
numCarriers = iqparse(get(handles.editNumCarriers, 'String'), 'scalar');
carrierSpacing = iqparse(get(handles.editCarrierSpacing, 'String'), 'scalar');
carrierOffset = iqparse(get(handles.editCarrierOffset, 'String'), 'vector');
magnitudes = iqparse(get(handles.editMagnitudes, 'String'), 'vector');
if dualPol
    quadErr = [iqparse(get(handles.editQuadErr, 'String'), 'scalar') iqparse(get(handles.editQuadErrY, 'String'), 'scalar')];
    iqskew = [iqparse(get(handles.editIQSkew, 'String'), 'scalar') iqparse(get(handles.editIQSkewY, 'String'), 'scalar')];
    gainImbalance = [iqparse(get(handles.editGainImbalance, 'String'), 'scalar') iqparse(get(handles.editGainImbalanceY, 'String'), 'scalar')];
else
    quadErr = iqparse(get(handles.editQuadErr, 'String'), 'scalar');
    iqskew = iqparse(get(handles.editIQSkew, 'String'), 'scalar');
    gainImbalance = iqparse(get(handles.editGainImbalance, 'String'), 'scalar');
end
xyGainImbalance = iqparse(get(handles.editXYgainImbalance, 'String'), 'scalar');
xySkew = iqparse(get(handles.editXYskew, 'String'), 'scalar');
correction = get(handles.checkboxCorrection, 'Value');
snlCorrection = get(handles.checkboxNLCorrection, 'Value');
phasenoise = get(handles.checkboxPhaseNoise, 'Value');
multiCarrier = get(handles.checkboxMulti, 'Value');
channelMapping = get(handles.pushbuttonChannelMapping, 'UserData');
segmentNum = iqparse(get(handles.editSegment, 'String'), 'scalar');
shift = [iqparse(get(handles.editShift, 'String'), 'scalar') iqparse(get(handles.editShiftY, 'String'), 'scalar')];
invert = [get(handles.checkboxInvert, 'Value') get(handles.checkboxInvertY, 'Value')];
if contains(dataType, 'PRBS')
    if strcmp(dataType, 'Std. PRBS')
        prbsList = get(handles.popupmenuPrbs, 'String');
        dataType = ['PRBS ' strrep(lower(prbsList{get(handles.popupmenuPrbs, 'Value')}), ' ', '')];
    elseif strcmp(dataType, 'Custom PRBS')
        dataType = ['PRBS ' get(handles.editCustomPrbs, 'String')];
    end
    if get(handles.checkboxPrbsDC, 'Value')
        dataType = [dataType ' (DC balanced)'];
    end
end
% get parameters for dual polarization
if dualPol
    dataTypeYList = get(handles.popupmenuDataY, 'String');
    dataTypeY = dataTypeYList{get(handles.popupmenuDataY, 'Value')};
    if strncmpi(dataTypeY, 'Same', 4)
        dataTypeY = dataType;
        dataContentY = dataContent;
        filenameY = filename;
    else
        dataContentY = iqparse(get(handles.editDataY, 'String'), 'vector');
        filenameY = get(handles.editFilenameY, 'String');
        if strcmp(dataTypeY, 'Std. PRBS')
            prbsListY = get(handles.popupmenuPrbsY, 'String');
            dataTypeY = ['PRBS ' strrep(lower(prbsListY{get(handles.popupmenuPrbsY, 'Value')}), ' ', '')];
        elseif strcmp(dataTypeY, 'Custom PRBS')
            dataTypeY = ['PRBS ' get(handles.editCustomPrbsY, 'String')];
        end
    end
else
    dataTypeY = [];
    dataContentY = [];
    filenameY = [];
end
% overwrite dataType with clockPat if it is given and set carrierOffset to
% zero, i.e. make clock pattern a baseband signal
if (exist('clockPat', 'var'))
    dataType = clockPat;
    carrierOffset = 0;
    % select all "unchecked" channels 
    channelMapping(:,1) = ~channelMapping(:,1) & ~channelMapping(:,2);
    channelMapping(:,2) = 0;
end
if (multiCarrier && isscalar(carrierOffset))
    carrierOffset = carrierOffset:carrierSpacing:(carrierOffset + (numCarriers - 1) * carrierSpacing);
end

if (exist('doCode', 'var') && doCode ~= 0)
    chMapStr = iqchannelsetup('arraystring', get(handles.pushbuttonChannelMapping, 'UserData'));
    segmentNum = iqparse(get(handles.editSegment, 'String'), 'scalar');
    magnitudes = svStr(magnitudes);
    fsStr = sprintf('fs = %s;\n', iqengprintf(sampleRate));
    if (length(carrierOffset) > 1)
        coStr = ['carrierOffset = [' strtrim(sprintf('%.7g ', carrierOffset)) '];\n'];
        carrierOffset = 'carrierOffset';
    else
        coStr = '';
        carrierOffset = strtrim(sprintf('%.7g', carrierOffset));
    end
    if (contains(dataType, 'User defined'))
        contentStr = sprintf(' ...\n    ''dataContent'', [%s], ', strtrim(sprintf('%g ', dataContent)));
    elseif (contains(dataType, 'from file'))
        contentStr = sprintf(' ...\n    ''filename'', ''%s'', ', filename);
    else
        contentStr = '';
    end
    if dualPol
        dataTypeYStr = sprintf('''dataY'', ''%s'', ', dataTypeY);
    else
        dataTypeYStr = '';
    end
    if dualPol && contains(dataTypeY, 'User defined')
        contentYStr = sprintf(' ...\n    ''dataContentY'', [%s], ', strtrim(sprintf('%g ', dataContentY)));
    elseif dualPol && contains(dataTypeY, 'from file')
        contentYStr = sprintf(' ...\n    ''filenameY'', ''%s'', ', filenameY);
    else
        contentYStr = '';
    end
    if dualPol
        shiftStr = ['[' strtrim(sprintf('%g ', shift)) ']'];
        invertStr = ['[' strtrim(sprintf('%g ', invert)) ']'];
    else
        shiftStr = strtrim(sprintf('%g ', shift(1)));
        invertStr = strtrim(sprintf('%g ', invert(1)));
    end
    if isa(modType, 'iqConstellation')
        cnstStr = modType.print('iqCnst = ');
        modType = 'iqCnst';
    else
        cnstStr = '';
        modType = sprintf('''%s''', modType);
    end
    iqdata = [sprintf([fsStr coStr cnstStr '[iqdata, newSampleRate, newNumSymbols, newNumSamples, chMap] = iqmod( ...\n' ...
    '    ''sampleRate'', fs, ''numSymbols'', %d, ...\n' ...
    '    ''data'', ''%s'', %s''modType'', %s, ''oversampling'', %g,%s%s ...\n' ...
    '    ''shift'', %s, ''invert'', %s, ...\n', ...
    '    ''filterType'', ''%s'', ''filterNsym'', %g, ...\n' ...
    '    ''filterBeta'', %g, ''carrierOffset'', %s, ''magnitude'', %s, ...\n' ...
    '    ''quadErr'', %s, ''iqskew'', %s, ''gainImbalance'', %s, ''XYgainImbalance'', %s, ...\n' ...
    '    ''xySkew'', %s, ''correction'', %d, ''snlCorrection'', %d, ''phasenoise'', %d, ...\n' ...
    '    ''function'', ''download'', ''channelMapping'', %s);\n\n' ...
    'iqdownload(iqdata, fs, ''channelMapping'', chMap, ''segmentNumber'', %d, ''marker'', []);\n'], ...
        numSymbols, dataType, dataTypeYStr, modType, oversampling, contentStr, contentYStr, shiftStr, invertStr, ...
        filterList{filterIdx}, filterNsym, filterBeta, carrierOffset, ...
        magnitudes, svStr(quadErr), svStr(iqskew), svStr(gainImbalance), svStr(xyGainImbalance), ...
        svStr(xySkew), correction, snlCorrection, phasenoise, chMapStr, segmentNum)];
else
    hMsgBox = msgbox('Calculating Waveform. Please wait...', 'Please wait...', 'replace');
    [iqdata, newSampleRate, newNumSymbols, newNumSamples, channelMapping] = iqmod('sampleRate', sampleRate, ...
        'numSymbols', numSymbols, ...
        'data', dataType, ...
        'modType', modType, ...
        'oversampling', oversampling, ...
        'dataContent', dataContent, ...
        'filename', filename, ...
        'dataY', dataTypeY, ...
        'dataContentY', dataContentY, ...
        'filenameY', filenameY, ...
        'shift', shift', ...
        'invert', invert, ...
        'filterType', filterList{filterIdx}, ...
        'filterNsym', filterNsym, ...
        'filterBeta', filterBeta, ...
        'carrierOffset', carrierOffset, ...
        'magnitude', magnitudes, ...
        'quadErr', quadErr, ...
        'iqSkew', iqskew, ...
        'gainImbalance', gainImbalance, ...
        'xyGainImbalance', xyGainImbalance, ...
        'xySkew', xySkew, ...
        'function', fct, ...
        'channelMapping', channelMapping, ...
        'correction', correction, ...
        'snlCorrection', snlCorrection, ...
        'phasenoise', phasenoise, ...
        'hMsgBox', hMsgBox, ...
        'segmentNumber', segmentNum);
    try close(hMsgBox); catch; end
    if (~exist('clockPat', 'var') || isempty(clockPat))
        assignin('base', 'iqdata', iqdata);
        assignin('base', 'fs', newSampleRate);
    end
    if (~isempty(newNumSamples) && newNumSamples ~= 0)
        set(handles.editNumSamples, 'String', sprintf('%d', newNumSamples));
        % do no update number of symbols in the GUI, so that the numbers don't
        % explode over time
        %set(handles.editNumSymbols, 'String', sprintf('%d', newNumSymbols));
        if (newSampleRate ~= sampleRate)
            iqTimedMessage(sprintf(['Waveform was re-sampled to match AWG granularity requirements.\n' ...
                'Sample Rate of %s will be used'], iqengprintf(newSampleRate, 8)));
            sampleRate = newSampleRate;
        end
        % set(handles.editSampleRate, 'String', iqengprintf(newSampleRate));
        [overN overD] = rat(oversampling);
        % for 1x oversampling, set marker every other symbol
        overN = max(overN, 2);
        % don't send markers faster than 10 GHz (DCA)
        maxTrig = 5e9;
        if (floor(sampleRate / maxTrig / overN) > 1)
            overN = overN * floor(sampleRate / maxTrig / overN);
        end
        h1 = floor(overN / 2);
        h2 = overN - h1;
        marker = repmat([15*ones(1,h1) zeros(1,h2)], 1, ceil(newNumSamples / overN));
        marker = marker(1:newNumSamples);
    else
        marker = [];
    end
end


function res = svStr(x)
% make a string with either a scalar or a vector
if isempty(x)
    res = '[]';
elseif isscalar(x)
    res = sprintf('%g', x);
else
    tmp = sprintf('%g ', x);
    res = sprintf('[%s]', tmp(1:end-1));
end


% --------------------------------------------------------------------
function menuLoadSettings_Callback(hObject, eventdata, handles)
% hObject    handle to menuLoadSettings (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
iqloadsettings(handles);
popupmenuData_Action([], [], handles);
% check multicarrier
checkboxMulti_Action([], [], handles);


% --------------------------------------------------------------------
function menuSaveSettings_Callback(hObject, eventdata, handles)
% hObject    handle to menuSaveSettings (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
iqsavesettings(handles);


% --------------------------------------------------------------------
function menuSaveWaveform_Callback(hObject, eventdata, handles)
% hObject    handle to menuSaveWaveform (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
[Y sampleRate oversampling marker] = calcModIQ(handles, 'save');
if (~isempty(Y))
    iqsavewaveform(Y, sampleRate);
end


function result = checkfields(hObject, eventdata, handles)
% This function verifies that all the fields have valid and consistent
% values. It is called from inside this script as well as from the
% iqconfig script when arbConfig changes (i.e. a different model or mode is
% selected). Returns 1 if all fields are OK, otherwise 0
result = 1;
arbConfig = loadArbConfig();

% --- generic checks
if (arbConfig.maxSegmentNumber <= 1)
    set(handles.editSegment, 'String', '1');
    set(handles.editSegment, 'Enable', 'off');
    set(handles.textSegment, 'Enable', 'off');
else
    set(handles.editSegment, 'Enable', 'on');
    set(handles.textSegment, 'Enable', 'on');
end
% --- channel mapping
dualPol = strcmp('on', get(handles.menuDualPolarization, 'Checked'));
if dualPol
    type = 'DualIQ';
else
    type = 'IQ';
end
%debugChMap('iqmod_gui: before iqchannelsetup', get(handles.pushbuttonChannelMapping, 'UserData'));
iqchannelsetup('setup', handles.pushbuttonChannelMapping, arbConfig, type);
%debugChMap('iqmod_gui: after iqchannelsetup', get(handles.pushbuttonChannelMapping, 'UserData'));
% --- editSampleRate
value = [];
try
    value = iqparse(get(handles.editSampleRate, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
if (isscalar(value) && (~isempty(find(value >= arbConfig.minimumSampleRate & value <= arbConfig.maximumSampleRate, 1))))
    if ~strcmp(arbConfig.model, 'S93072B_PNA')
        set(handles.editSampleRate,'BackgroundColor','white');
    else % special case: S93072B
        if( isfield(arbConfig,'SampleRateMultiple') && arbConfig.SampleRateMultiple ~= 0 && mod(arbConfig.maximumSampleRate, value) ~=0)
            set(handles.editSampleRate,'BackgroundColor','red');
             n = round(arbConfig.maximumSampleRate/value);
             samplerate = arbConfig.maximumSampleRate/n;
            warndlg(sprintf('Sample rate must be 19.2G/N, where N is an integer. Suggested %s', iqengprintf(samplerate)));
        else
            set(handles.editSampleRate,'BackgroundColor','white');
        end
    end
else
    set(handles.editSampleRate,'BackgroundColor','red');
end
% --- oversampling
oversampling = iqparse(get(handles.editOversampling, 'String'), 'scalar');
if (isscalar(oversampling) && oversampling >= 1 && oversampling <= 100000)
    set(handles.editOversampling, 'BackgroundColor', 'white');
else
    set(handles.editOversampling, 'BackgroundColor', 'red');
end
% --- editSymbolRate
value = [];
try
    value = iqparse(get(handles.editSymbolRate, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
if (isscalar(value) && value >= 1e3 && value <= 100e9)
end
checkCarrierSpacingSymbolRate(handles);
% --- editSegment
value = [];
try
    value = iqparse(get(handles.editSegment, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
    result = 0;
end
if (isscalar(value) && value >= 1 && value <= arbConfig.maxSegmentNumber)
    set(handles.editSegment,'BackgroundColor','white');
else
    set(handles.editSegment,'BackgroundColor','red');
    result = 0;
end



function editQuadErr_Callback(hObject, eventdata, handles)
% hObject    handle to editQuadErr (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editQuadErr as text
%        str2double(get(hObject,'String')) returns contents of editQuadErr as a double
value = [];
arbConfig = loadArbConfig();
try
    value = iqparse(get(handles. editQuadErr, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
if (isscalar(value) && value >= -360 && value <= 360)
    set(handles. editQuadErr, 'Background', 'white');
else
    set(handles. editQuadErr, 'Background', 'red');
end




% --- Executes during object creation, after setting all properties.
function editQuadErr_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editQuadErr (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


% --------------------------------------------------------------------
function menuGenerateCode_Callback(hObject, eventdata, handles)
% hObject    handle to menuGenerateCode (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
code = calcModIQ(handles, 'none', 1);
iqgeneratecode(handles, code);


% --- Executes on button press in pushbuttonChannelMapping.
function pushbuttonChannelMapping_Callback(hObject, eventdata, handles)
pushbuttonChannelMapping_Action(hObject, eventdata, handles);


%---------------------------------------------------------------------
function pushbuttonChannelMapping_Action(hObject, eventdata, handles)
% hObject    handle to pushbuttonChannelMapping (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
arbConfig = loadArbConfig();
dualPol = strcmp('on', get(handles.menuDualPolarization, 'Checked'));
if dualPol
    format = 'DualIQ';
else
    format = 'IQ';
end
[val, str] = iqchanneldlg(get(handles.pushbuttonChannelMapping, 'UserData'), arbConfig, handles.iqtool, format);
if (~isempty(val))
    set(handles.pushbuttonChannelMapping, 'UserData', val);
    set(handles.pushbuttonChannelMapping, 'String', str);
end


% --- Executes on selection change in popupmenuData.
function popupmenuData_Callback(hObject, eventdata, handles)
popupmenuData_Action(hObject, eventdata, handles);


%---------------------------------------------------------------------
function popupmenuData_Action(hObject, eventdata, handles)
% hObject    handle to popupmenuData (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
popupmenuData_Changed(handles);


function popupmenuData_Changed(handles)
dataTypeList = cellstr(get(handles.popupmenuData, 'String'));
dataType = dataTypeList{get(handles.popupmenuData, 'Value')};
if contains(dataType, 'User defined')
    set(handles.textData, 'String', 'Data content');
    set(handles.editData, 'Visible', 'on');
    set(handles.editData, 'Visible', 'on');
    set(handles.editFilename, 'Visible', 'off');
    set(handles.pushbuttonFilename, 'Visible', 'off');
    set(handles.editCustomPrbs, 'Visible', 'off');
    set(handles.popupmenuPrbs, 'Visible', 'off');
elseif contains(dataType, 'from file')
    set(handles.textData, 'String', 'Filename');
    set(handles.editData, 'Visible', 'off');
    set(handles.editFilename, 'Visible', 'on');
    set(handles.editFilename, 'Enable', 'on');
    set(handles.pushbuttonFilename, 'Visible', 'on');
    set(handles.editCustomPrbs, 'Visible', 'off');
    set(handles.popupmenuPrbs, 'Visible', 'off');
elseif contains(dataType, 'Custom PRBS')
    set(handles.textData, 'String', 'PRBS Polynomial');
    set(handles.editData, 'Visible', 'off');
    set(handles.editFilename, 'Visible', 'off');
    set(handles.pushbuttonFilename, 'Visible', 'off');
    set(handles.editCustomPrbs, 'Visible', 'on');
    set(handles.popupmenuPrbs, 'Visible', 'off');
elseif contains(dataType, 'Std. PRBS')
    set(handles.textData, 'String', 'PRBS Polynomial');
    set(handles.editData, 'Visible', 'off');
    set(handles.editFilename, 'Visible', 'off');
    set(handles.pushbuttonFilename, 'Visible', 'off');
    set(handles.editCustomPrbs, 'Visible', 'off');
    set(handles.popupmenuPrbs, 'Visible', 'on');
    set(handles.popupmenuPrbs, 'Enable', 'on');
else % random, clock, counter
    set(handles.editData, 'Visible', 'off');
    set(handles.editFilename, 'Visible', 'off');
    set(handles.pushbuttonFilename, 'Visible', 'off');
    set(handles.editCustomPrbs, 'Visible', 'off');
    set(handles.popupmenuPrbs, 'Visible', 'off');
end
if contains(dataType, 'PRBS')
    set(handles.checkboxPrbsDC, 'Visible', 'on');
    set(handles.textShiftInvert', 'String', 'Shift / Invert / DC bal.');
else
    set(handles.checkboxPrbsDC, 'Visible', 'off');
    set(handles.textShiftInvert', 'String', 'Shift / Invert');
end
dualPol = strcmp('on', get(handles.menuDualPolarization, 'Checked'));
winPos = get(handles.iqtool, 'Position');
if ~dualPol
    winPos(3) = 278;
    set(handles.iqtool, 'Position', winPos);
    set(handles.textYPolarization, 'Visible', 'off');
    set(handles.popupmenuDataY, 'Visible', 'off');
    set(handles.checkboxInvertY, 'Visible', 'off');
    set(handles.editShiftY, 'Visible', 'off');
    set(handles.editQuadErrY, 'Visible', 'off');
    set(handles.editIQSkewY, 'Visible', 'off');
    set(handles.editGainImbalanceY, 'Visible', 'off');
    set(handles.editDataY, 'Visible', 'off');
    set(handles.editFilenameY, 'Visible', 'off');
    set(handles.pushbuttonFilenameY, 'Visible', 'off');
    set(handles.editCustomPrbsY, 'Visible', 'off');
    set(handles.popupmenuPrbsY, 'Visible', 'off');
    set(handles.textXYgainImbalance, 'Visible', 'off');
    set(handles.textXYskew, 'Visible', 'off');
else
    winPos(3) = 319;
    set(handles.iqtool, 'Position', winPos);
    set(handles.textYPolarization, 'Visible', 'on');
    set(handles.popupmenuDataY, 'Visible', 'on');
    set(handles.checkboxInvertY, 'Visible', 'on');
    set(handles.editShiftY, 'Visible', 'on');
    set(handles.editQuadErrY, 'Visible', 'on');
    set(handles.editIQSkewY, 'Visible', 'on');
    set(handles.editGainImbalanceY, 'Visible', 'on');
    set(handles.textXYgainImbalance, 'Visible', 'on');
    set(handles.textXYskew, 'Visible', 'on');
    dataYTypeList = cellstr(get(handles.popupmenuDataY, 'String'));
    dataYType = dataYTypeList{get(handles.popupmenuDataY, 'Value')};
    if contains(dataYType, 'Same as')
        set(handles.editDataY, 'Visible', 'off');
        set(handles.editFilenameY, 'Visible', 'off');
        set(handles.pushbuttonFilenameY, 'Visible', 'off');
        set(handles.editCustomPrbsY, 'Visible', 'off');
        set(handles.popupmenuPrbsY, 'Visible', 'off');
    elseif contains(dataYType, 'User defined')
        set(handles.editDataY, 'Visible', 'on');
        set(handles.editDataY, 'Enable', 'on');
        set(handles.editFilenameY, 'Visible', 'off');
        set(handles.pushbuttonFilenameY, 'Visible', 'off');
        set(handles.editCustomPrbsY, 'Visible', 'off');
        set(handles.popupmenuPrbsY, 'Visible', 'off');
    elseif contains(dataYType, 'from file')
        set(handles.editDataY, 'Visible', 'off');
        set(handles.editFilenameY, 'Visible', 'on');
        set(handles.editFilenameY, 'Enable', 'on');
        set(handles.pushbuttonFilenameY, 'Visible', 'on');
        set(handles.editCustomPrbsY, 'Visible', 'off');
        set(handles.popupmenuPrbsY, 'Visible', 'off');
    elseif contains(dataYType, 'Custom PRBS')
        set(handles.editDataY, 'Visible', 'off');
        set(handles.editFilenameY, 'Visible', 'off');
        set(handles.pushbuttonFilenameY, 'Visible', 'off');
        set(handles.editCustomPrbsY, 'Visible', 'on');
        set(handles.popupmenuPrbsY, 'Visible', 'off');
    elseif contains(dataYType, 'Std. PRBS')
        set(handles.editDataY, 'Visible', 'off');
        set(handles.editFilenameY, 'Visible', 'off');
        set(handles.pushbuttonFilenameY, 'Visible', 'off');
        set(handles.editCustomPrbsY, 'Visible', 'off');
        set(handles.popupmenuPrbsY, 'Visible', 'on');
        set(handles.popupmenuPrbsY, 'Enable', 'on');
    else % random, clock, counter
        set(handles.editDataY, 'Visible', 'off');
        set(handles.editFilenameY, 'Visible', 'off');
        set(handles.pushbuttonFilenameY, 'Visible', 'off');
        set(handles.editCustomPrbsY, 'Visible', 'off');
        set(handles.popupmenuPrbsY, 'Visible', 'off');
    end
    if contains(dataYType, 'PRBS')
        set(handles.checkboxPrbsDCY, 'Visible', 'on');
    else
        set(handles.checkboxPrbsDCY, 'Visible', 'off');
    end
end
if contains(dataType, 'PRBS')
    prbsChanged(handles);
end


function prbsChanged(handles)
dataTypeList = cellstr(get(handles.popupmenuData, 'String'));
dataType = dataTypeList{get(handles.popupmenuData, 'Value')};
if get(handles.checkboxPrbsDC, 'Value')
    dcStr = '';
else
    dcStr = '-1';
end
if strcmp(dataType, 'Std. PRBS')
    prbsList = get(handles.popupmenuPrbs, 'String');
    prbsStr = prbsList{get(handles.popupmenuPrbs, 'Value')};
    poly = checkPrbs(prbsStr);
elseif strcmp(dataType, 'Custom PRBS')
    poly = checkPrbs(get(handles.editCustomPrbs, 'String'));
else
    poly = [];
end
if ~isempty(poly)
    set(handles.editNumSymbols, 'String', sprintf('2^%d%s', poly(1), dcStr));
end


% --- Executes during object creation, after setting all properties.
function popupmenuData_CreateFcn(hObject, eventdata, handles)
% hObject    handle to popupmenuData (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: popupmenu controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editIQSkew_Callback(hObject, eventdata, handles)
% hObject    handle to editIQSkew (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editIQSkew as text
%        str2double(get(hObject,'String')) returns contents of editIQSkew as a double
value = [];
arbConfig = loadArbConfig();
try
    value = iqparse(get(handles.editIQSkew, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
if (isscalar(value) && value >= -1 && value <= 1)
    set(handles.editIQSkew, 'Background', 'white');
else
    set(handles.editIQSkew, 'Background', 'red');
end



% --- Executes during object creation, after setting all properties.
function editIQSkew_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editIQSkew (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editGainImbalance_Callback(hObject, eventdata, handles)
% hObject    handle to editGainImbalance (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editGainImbalance as text
%        str2double(get(hObject,'String')) returns contents of editGainImbalance as a double
value = [];
arbConfig = loadArbConfig();
try
    value = iqparse(get(handles.editGainImbalance, 'String'), 'scalar');
catch ex
    msgbox(ex.message);
end
if (isscalar(value) && value >= -30 && value <= 30)
    set(handles.editGainImbalance, 'Background', 'white');
else
    set(handles.editGainImbalance, 'Background', 'red');
end


% --- Executes during object creation, after setting all properties.
function editGainImbalance_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editGainImbalance (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


function editData_Callback(hObject, eventdata, handles)
% hObject    handle to editData (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editData as text
%        str2double(get(hObject,'String')) returns contents of editData as a double


% --- Executes during object creation, after setting all properties.
function editData_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editData (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


% --- Executes on button press in pushbuttonFilename.
function pushbuttonFilename_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonFilename (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
if (isfield(handles, 'LastFileName'))
    lastFilename = handles.LastFileName;
else
    lastFilename = '';
end
types = '*.ptrn;*.txt;*.csv';
try
[FileName,PathName] = uigetfile(types, 'Select pattern file to load', lastFilename);
if(FileName~=0)
   FileName = strcat(PathName,FileName);
   set(handles.editFilename, 'String', FileName);
   editFilename_Action([], eventdata, handles);
   % remember pathname for next time
   handles.LastFileName = FileName;
   guidata(hObject, handles);
end   
catch ex
end


function editFilename_Callback(hObject, eventdata, handles)
editFilename_Action(hObject, eventdata, handles);


%---------------------------------------------------------------------
function editFilename_Action(hObject, eventdata, handles)
% hObject    handle to editFilename (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
filename = get(handles.editFilename, 'String');
try
    f = fopen(filename, 'r');
    fclose(f);
catch ex
    errordlg(sprintf('Can''t open %s', filename'));
end


% --- Executes during object creation, after setting all properties.
function editFilename_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editFilename (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end

function menuClock_Callback(hObject, eventdata, handles)
menuClock_Action(hObject, eventdata, handles);


%---------------------------------------------------------------------
function menuClock_Action(hObject, eventdata, handles)
set(handles.menuNoClock, 'Checked', 'off');
set(handles.menuClock2, 'Checked', 'off');
set(handles.menuClock3, 'Checked', 'off');
set(handles.menuClock4, 'Checked', 'off');
set(handles.menuClock5, 'Checked', 'off');
set(handles.menuClock6, 'Checked', 'off');
set(handles.menuClock7, 'Checked', 'off');
set(handles.menuClock8, 'Checked', 'off');
set(handles.menuClock16, 'Checked', 'off');
set(handles.menuClockOnce, 'Checked', 'off');
set(hObject, 'Checked', 'on');
if (hObject ~= handles.menuNoClock)
    chm = get(handles.pushbuttonChannelMapping, 'UserData');
    if (length(find(sum(chm'))) == size(chm,1) && size(chm,1) > 1)
        hMsgBox = msgbox(['In order to generate a clock signal, please un-check at least one channel in the "Download" window. ' ...
                          'The clock signal will be generated on the unchecked channel(s)']);
        pushbuttonChannelMapping_Action([], [], handles);
        try
            close(hMsgBox);
        catch
        end
    end
end


% --------------------------------------------------------------------
function menuNoClock_Callback(hObject, eventdata, handles)
% hObject    handle to menuNoClock (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
menuClock_Action(hObject, eventdata, handles);


% --- Executes on button press in pushbuttonPlotConstellation.
function pushbuttonPlotConstellation_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonPlotConstellation (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
modTypeList = get(handles.popupmenuModType, 'String');
modTypeIdx = get(handles.popupmenuModType, 'Value');
modType = modTypeList{modTypeIdx};
cnst = get(handles.pushbuttonPlotConstellation, 'UserData');
if strcmp(modType, 'Custom')
    cnst = iqConstellationDlg(0, cnst);
else
    cnst = iqConstellationDlg(0, modType);
end
if ~isempty(cnst)
    cnst.name = 'Custom';
    set(handles.pushbuttonPlotConstellation, 'UserData', cnst);
    if ~any(strcmp('Custom', modTypeList))
        modTypeList{end+1} = 'Custom';
        set(handles.popupmenuModType, 'String', modTypeList);
    end
    set(handles.popupmenuModType, 'Value', find(strcmp('Custom', modTypeList), 1));
end


% --------------------------------------------------------------------
function menuVSA_Callback(hObject, eventdata, handles)
% hObject    handle to menuVSA (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)


% --------------------------------------------------------------------
function menuShowInVSA_noSetup_Callback(hObject, eventdata, handles)
% hObject    handle to menuShowInVSA_noSetup (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
showInVSA(hObject, handles, 0);

% --------------------------------------------------------------------
function menuShowInVSA_Callback(hObject, eventdata, handles)
% hObject    handle to menuShowInVSA (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
showInVSA(hObject, handles, 1);


% --------------------------------------------------------------------
function menuDCAVSA_Callback(hObject, eventdata, handles)
menuDCAVSA_Action(hObject, eventdata, handles);


%---------------------------------------------------------------------
function menuDCAVSA_Action(hObject, eventdata, handles)
% hObject    handle to menuDCAVSA (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
fc = iqparse(get(handles.editCarrierOffset, 'String'), 'vector');
if (length(fc) ~= 1)
    errordlg('This function is not supported for multi-carrier signals. Please specify a single value as a carrier offset');
    return;
end
numSamples = iqparse(get(handles.editNumSamples, 'String'), 'scalar');
oversampling = iqparse(get(handles.editOversampling, 'String'), 'scalar');
[n,d] = rat(oversampling, handles.os_resolution);
oversampling = n / d;
numSymbols = round(numSamples / oversampling);
symbolRate = iqparse(get(handles.editSymbolRate, 'String'), 'scalar');
if (symbolRate < 1e9)
    errordlg('This function is only supported for symbol rates >= 1 GSym/s');
    return;
end
% avg and spb are hardcoded for now (don't ask too many questions)
avg = 6;
if (fc ~= 0) % signal on a carrier
    if (symbolRate/2 > fc)
        errordlg('Carrier Frequency must be greater than SymbolRate/2');
        return;
    end
    % samples per symbol depends on the carrier frequency
    spb = round(80 / symbolRate * fc);
else % baseband
    % samples per symbol
    spb = 8;
end
% get menu setting for clock generation 
[div,~] = getDivClock(handles);
if (div ~= 1)
    % divided clock is specified
    defaultPTBFreq = {iqengprintf(symbolRate / div)};
else
    % divided clock is not specified
    defaultPTBFreq = {'8e9'};
end
if (isfield(handles, 'defaultPTBFreq') && iscell(handles.defaultPTBFreq) && length(handles.defaultPTBFreq) == 1)
    defaultPTBFreq = handles.defaultPTBFreq;
end
ptbFreqStr = inputdlg({'Please enter the PTB (resp. DCA-M clock) frequency'}, ...
    'PTB clock frequency', 1, defaultPTBFreq);
if (isempty(ptbFreqStr))
    return;
end
% remember the current PTB Frequency
handles.defaultPTBFreq = ptbFreqStr;
guidata(hObject, handles);
ptbFreq = str2double(ptbFreqStr);
if (mod(symbolRate, ptbFreq) == 0)
    % if symbolRate is an integer multiple of ptbFreq, use the true symbol rate for the DCA
    dcaSymbolRate = symbolRate;
    dcaSpb = spb;
else
    % if not, pretend that the symbol rate = PTB rate, so that the DCA does not complain.
    % the number of symbols will be re-calculated
    dcaSymbolRate = ptbFreq;
    if (mod((dcaSymbolRate * numSymbols / symbolRate), 1) ~= 0)
        errordlg(sprintf(['This combination of PTB clock frequency and number of symbols does not work. ' ...
            'Either the symbol rate must be evenly divisible by the PTB clock frequency (%s / %s = %.2f)\n    - or -\n' ...
            'the PTB frequency times the number of symbols must be evenly divisible by the symbol rate. ' ...
            '(%s * %d / %s = %.2f)'], ...
            iqengprintf(symbolRate), iqengprintf(ptbFreq), symbolRate/ptbFreq, ...
            iqengprintf(dcaSymbolRate), numSymbols, iqengprintf(symbolRate), dcaSymbolRate * numSymbols / symbolRate));
        return;
    end
    dcaSpb = round(spb * symbolRate / dcaSymbolRate);
end

%--- allow the user to adjust samples per UI manually ---
% dcaSpbStr = inputdlg({'Please enter the SPB for DCA'}, ...
%     'SPB', 1, {num2str(dcaSpb)});
% if (isempty(dcaSpbStr))
%     return;
% end
% dcaSpb = str2double(dcaSpbStr);

% calculate the number of samples that will be captured in the scope
dcaSamples = numSymbols * spb;
% rough formula for the number of seconds it takes to capture the signal on a DCA-X
captureTime = avg * dcaSamples / 35000;
if (captureTime > 60)
    res = questdlg(sprintf('With %d symbols, the capture time on the DCA will be approx. %d seconds. Do you still want to run the analysis?', numSymbols, round(captureTime)), 'Long Capture Time', 'Yes');
    if (~strcmp(res, 'Yes'))
        return;
    end
end
% ask the user for the channelmapping
channelMapping = get(handles.pushbuttonChannelMapping, 'UserData');
if (fc == 0 && length(find(sum(abs(channelMapping), 1))) < 2)
    errordlg('Please configure both I *and* Q to be downloaded to the AWG');
    return;
end
if (div > 1 && length(find(sum(abs(channelMapping), 2))) >= 4)
    errordlg('Please uncheck at least one channel in order to generate a clock signal on that channel');
    return;
end
if (fc ~= 0)
    defaultDCAChannelConnection = {'1A'};
    if (isfield(handles, 'defaultDCAChannelConnection') && iscell(handles.defaultDCAChannelConnection) && length(handles.defaultDCAChannelConnection) == 1)
        defaultDCAChannelConnection = handles.defaultDCAChannelConnection;
    end
    chan = inputdlg({'Signal connected to DCA channel'}, 'DCA connections', 1, defaultDCAChannelConnection);
    if (isempty(chan))
        return;
    end
    % remember the current DCA channel mapping
    handles.defaultDCAChannelConnection = chan;
    guidata(hObject, handles);
else
    defaultDCAChannelConnection = {'1A', '2A'};
    if (isfield(handles, 'defaultDCAChannelConnection') && iscell(handles.defaultDCAChannelConnection) && length(handles.defaultDCAChannelConnection) == 2)
        defaultDCAChannelConnection = handles.defaultDCAChannelConnection;
    end
    chan = inputdlg({'"I" is connected to DCA channel', '"Q" is connected to DCA channel'}, 'DCA connections', 1, defaultDCAChannelConnection);
    if (isempty(chan))
        return;
    end
    % remember the current DCA channel mapping
    handles.defaultDCAChannelConnection = chan;
    guidata(hObject, handles);
end
vsaApp = vsafunc([], 'open');
if (isempty(vsaApp))
    return;
end
vsafunc(vsaApp, 'stop');
% just to be sure: download the waveform
% pushbuttonDownload_Callback(hObject, eventdata, handles);
% autoscale
maxAmpl = -2;
arbConfig = loadArbConfig();
% acquire the signal from the DCA
hMsgBox = msgbox('Acquiring data from DCA. Please wait...', 'Please wait...');
[sig, fsDCA] = iqreaddca(arbConfig, chan, [], numSymbols/symbolRate, avg, maxAmpl, ptbFreq, dcaSymbolRate, dcaSpb, 'MAX', 1, 1);
try close(hMsgBox); catch ex; end
if (fc ~= 0)
    if (size(sig,2) ~= 1)
        errordlg('Waveform capture from DCA failed. Expected one trace. Please check connections');
        return;
    end
    sig = sig - mean(sig);
    sigDCA = complex(sig, zeros(size(sig)));
else
    if (size(sig,2) ~= 2)
        errordlg('Waveform capture from DCA failed. Expected two traces. Please check connections');
        return;
    end
    sig(:,1) = sig(:,1) - mean(sig(:,1));
    sig(:,2) = sig(:,2) - mean(sig(:,2));
    sigDCA = complex(sig(:,1),sig(:,2));
end
% make the result visible in the MATLAB workspace for further manual analysis
assignin('base', 'fsDCA', fsDCA);
assignin('base', 'sigDCA', sigDCA);
% configure VSA
handles.lastDownload = 'DCA';
guidata(hObject, handles);
modTypeList = get(handles.popupmenuModType, 'String');
modType = modTypeList{get(handles.popupmenuModType, 'Value')};
iqCnst = get(handles.pushbuttonPlotConstellation, 'UserData');
if ~isempty(iqCnst) && isa(iqCnst, 'iqConstellation') && strcmp(modType, iqCnst.name)
    modType = iqCnst;
end
filterList = get(handles.popupmenuFilter, 'String');
filterIdx = get(handles.popupmenuFilter, 'Value');
filterBeta = iqparse(get(handles.editFilterBeta, 'String'), 'scalar');
resultLength = iqparse(get(handles.editResultLength, 'String'), 'scalar');
filterLength = iqparse(get(handles.editFilterLength, 'String'), 'scalar');
convergence = iqparse(get(handles.editConvergence, 'String'), 'scalar');
vsaApp = vsafunc([], 'open');
if (~isempty(vsaApp))
    demodType = 'CustomIQ'; % 'DigDemod';
    hMsgBox = msgbox('Configuring VSA software. Please wait...');
    vsafunc(vsaApp, 'preset');
    vsafunc(vsaApp, 'input', 1);
    vsafunc(vsaApp, 'load', sigDCA, fsDCA);
    vsafunc(vsaApp, demodType, modType, symbolRate, filterList{filterIdx}, filterBeta, resultLength);
    vsafunc(vsaApp, 'equalizer', false, filterLength, convergence, demodType);
    if (strcmp(filterList{filterIdx}, 'Gaussian'))
        spanScale = 9 * filterBeta;
    else
        spanScale = 1 + filterBeta;
    end
    vsafunc(vsaApp, 'freq', fc, symbolRate * spanScale, 51201, 'flattop', 3);
    vsafunc(vsaApp, 'trace', 4, demodType);
    vsafunc(vsaApp, 'start', 1);
    vsafunc(vsaApp, 'autoscale');
    try
        close(hMsgBox);
    catch
    end
end


% --------------------------------------------------------------------
%
% Special treatment for M8131A
% This is no longer necessary since VSA is integrated with M8131A
%
function menuM8131A_VSA_Callback(hObject, eventdata, handles)
% hObject    handle to menuM8131A_VSA (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
fc = iqparse(get(handles.editCarrierOffset, 'String'), 'vector');
if (length(fc) ~= 1)
    errordlg('This function is not supported for multi-carrier signals. Please specify a single value as a carrier offset');
    return;
end
% if (fc == 0)
%     errordlg('This function only supports RF signals at this time - please set a non-zero "Carrier Offset"');
%     return;
% end
numSamples = iqparse(get(handles.editNumSamples, 'String'), 'scalar');
oversampling = iqparse(get(handles.editOversampling, 'String'), 'scalar');
[n,d] = rat(oversampling, handles.os_resolution);
oversampling = n / d;
numSymbols = round(numSamples / oversampling);
symbolRate = iqparse(get(handles.editSymbolRate, 'String'), 'scalar');
if (fc ~= 0) % signal on a carrier
    if (symbolRate/2 > fc)
        errordlg('Carrier Frequency must be greater than SymbolRate/2');
        return;
    end
end
% ask the user for the channelmapping
channelMapping = get(handles.pushbuttonChannelMapping, 'UserData');
if (fc == 0 && length(find(sum(abs(channelMapping), 1))) < 2)
    errordlg('Please configure both I *and* Q to be downloaded to the AWG');
    return;
end
if (fc ~= 0)
    defaultScopeChannel = {'1'};
    if (isfield(handles, 'defaultScopeChannel') && iscell(handles.defaultScopeChannel) && length(handles.defaultScopeChannel) == 1)
        defaultScopeChannel = handles.defaultScopeChannel;
    end
    chan = inputdlg({'Signal connected to M8131A channel'}, 'M8131A channel connections', 1, defaultScopeChannel);
    if (isempty(chan))
        return;
    end
    % remember the current DCA channel mapping
    handles.defaultScopeChannel = chan;
    guidata(hObject, handles);
else
    defaultScopeChannel = {'1', '3'};
    if (isfield(handles, 'defaultScopeChannel') && iscell(handles.defaultScopeChannel) && length(handles.defaultScopeChannel) == 2)
        defaultScopeChannel = handles.defaultScopeChannel;
    end
    chan = inputdlg({'"I" is connected to M8131A channel', '"Q" is connected to M8131A channel'}, 'M8131A channel connections', 1, defaultScopeChannel);
    if (isempty(chan))
        return;
    end
    % remember the current DCA channel mapping
    handles.defaultScopeChannel = chan;
    guidata(hObject, handles);
end
vsaApp = vsafunc([], 'open');
if (isempty(vsaApp))
    return;
end
vsafunc(vsaApp, 'stop');
% just to be sure: download the waveform
% pushbuttonDownload_Callback(hObject, eventdata, handles);
% autoscale
maxAmpl = -2;
arbConfig = loadArbConfig();
% acquire the signal from the DCA
hMsgBox = msgbox('Acquiring data from M8131A. Please wait...', 'Please wait...');
duration = numSymbols/symbolRate;
% check max capture time for M8131A
maxDuration = 8.1920e-05;
if (duration > maxDuration)
    duration = maxDuration;
    warndlg(sprintf('Waveform exceeds M8131A capture memory. Only %s us will be captured', iqengprintf(duration * 1e6)));
end
[sig, fsScope] = iqreadM8131A(arbConfig, chan, [], duration, 0, maxAmpl);
try close(hMsgBox); catch ex; end
if (fc ~= 0)
    if (size(sig,2) ~= 1)
        errordlg('Waveform capture from M8131A failed. Expected one trace. Please check connections');
        return;
    end
    sigScope = complex(sig, zeros(size(sig)));
else
    if (size(sig,2) ~= 2)
        errordlg('Waveform capture from M8131A failed. Expected two traces. Please check connections');
        return;
    end
    sigScope = complex(sig(:,1),sig(:,2));
end
% make the result visible in the MATLAB workspace for further manual analysis
assignin('base', 'fsScope', fsScope);
assignin('base', 'sigScope', sigScope);
% configure VSA
handles.lastDownload = 'VSA';
guidata(hObject, handles);
modTypeList = get(handles.popupmenuModType, 'String');
modTypeIdx = get(handles.popupmenuModType, 'Value');
filterList = get(handles.popupmenuFilter, 'String');
filterIdx = get(handles.popupmenuFilter, 'Value');
filterBeta = iqparse(get(handles.editFilterBeta, 'String'), 'scalar');
resultLength = iqparse(get(handles.editResultLength, 'String'), 'scalar');
filterLength = iqparse(get(handles.editFilterLength, 'String'), 'scalar');
convergence = iqparse(get(handles.editConvergence, 'String'), 'scalar');
vsaApp = vsafunc([], 'open');
if (~isempty(vsaApp))
    demodType = 'CustomIQ'; % 'DigDemod';
    hMsgBox = msgbox('Configuring VSA software. Please wait...');
    vsafunc(vsaApp, 'preset');
    vsafunc(vsaApp, 'input', 1);
    vsafunc(vsaApp, 'load', sigScope, fsScope);
    vsafunc(vsaApp, demodType, modTypeList{modTypeIdx}, symbolRate, filterList{filterIdx}, filterBeta, resultLength);
    vsafunc(vsaApp, 'equalizer', false, filterLength, convergence, demodType);
    if (strcmp(filterList{filterIdx}, 'Gaussian'))
        spanScale = 9 * filterBeta;
    else
        spanScale = 1 + filterBeta;
    end
    vsafunc(vsaApp, 'freq', fc, symbolRate * spanScale, 51201, 'flattop', 3);
    vsafunc(vsaApp, 'trace', 4, demodType);
    vsafunc(vsaApp, 'start', 1);
    vsafunc(vsaApp, 'autoscale');
    try
        close(hMsgBox);
    catch
    end
end


% --- Executes when user attempts to close iqtool.
function iqtool_CloseRequestFcn(hObject, eventdata, handles)
% hObject    handle to iqtool (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hint: delete(hObject) closes the figure
delete(hObject);


% --- Executes on button press in pushbuttonMagEqualize.
function pushbuttonMagEqualize_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonMagEqualize (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

multicarrier = get(handles.checkboxMulti, 'Value');

if multicarrier
    
    symbolRate = iqparse(get(handles.editSymbolRate, 'String'), 'scalar');
    modTypeList = get(handles.popupmenuModType, 'String');
    modTypeIdx = get(handles.popupmenuModType, 'Value');
    filterList = get(handles.popupmenuFilter, 'String');
    filterIdx = get(handles.popupmenuFilter, 'Value');
    filterBeta = iqparse(get(handles.editFilterBeta, 'String'), 'scalar');
    numCarriers = iqparse(get(handles.editNumCarriers, 'String'), 'scalar');
    carrierSpacing = iqparse(get(handles.editCarrierSpacing, 'String'), 'scalar');
    carrierOffset = iqparse(get(handles.editCarrierOffset, 'String'), 'vector');
    resultLength = iqparse(get(handles.editResultLength, 'String'), 'scalar');
    oldAdjustment = iqparse(get(handles.editMagnitudes, 'String'), 'vector');
    vsaFc = iqparse(get(handles.editFc, 'String'), 'scalar');
    recal = get(handles.checkboxCorrection, 'Value');
    
    if (recal) 
        try
            multiCalParams = getappdata(0,'multiCalParameters');            
        catch 
            msgbox('Carrier Parameters not specified forsignal');
            
        end
    end
    
    useHW = 1;
    powers =[];
    
    if (length(carrierOffset) == 1 && numCarriers > 1)
        carrierOffset = carrierOffset:carrierSpacing:(carrierOffset + (numCarriers - 1) * carrierSpacing);
    else
        carrierOffset = sort(carrierOffset);
    end
    
    % Make sure our array is the right size, fill with zeros to num carriers
    if length(oldAdjustment) < numCarriers
        oldAdjustment(numCarriers) = 0;
    end
    
    doLastDownload(hObject, eventdata, handles);
    for i = 1:numCarriers;
        
        %set up VSA
        fc = carrierOffset(i)+ vsaFc;
        
        if (recal)
            range = cell2mat(multiCalParams(i,5));
            mixerMode = char(multiCalParams(i,6));
            customFilterFile = char(multiCalParams(i,7));
        else
            range = ''; % autorange
            mixerMode = 'Normal';
            customFilterFile = '';
        end        
        
        result = iqvsabandpower('symbolRate', symbolRate, ...
            'modType', modTypeList{modTypeIdx}, ...
            'filterType', filterList{filterIdx}, ...
            'filterBeta', filterBeta, ...
            'fc', fc , ...
            'resultLength', resultLength, ...
            'useHW', useHW, ...
            'mixerMode', mixerMode, ...
            'customFilterFile', customFilterFile, ...
            'range', range, ...
            'doOBP', 1);
        
        if (result ~= 0)
            powers = [powers result];
        end
    end
    
    minPower = min(powers);
    relativeMags = '';
    
    %Update the correction values
    for i= 1:numCarriers
        adjustment = num2str((oldAdjustment(i) + (minPower - powers(i))), '%2.3f');
        relativeMags = strcat(relativeMags, adjustment,',');
    end
    % delete last comma
    relativeMags = relativeMags(1:end-1);
    set(handles.editMagnitudes, 'String', relativeMags);
    
    % download data again
    doLastDownload(hObject, eventdata, handles);
end


% --------------------------------------------------------------------
function multiCarrierControl_Callback(hObject, eventdata, handles)
% hObject    handle to multiCarrierControl (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
symbolRate = iqparse(get(handles.editSymbolRate, 'String'), 'scalar');
filterBeta = iqparse(get(handles.editFilterBeta, 'String'), 'scalar');
numCarriers = iqparse(get(handles.editNumCarriers, 'String'), 'scalar');
carrierSpacing = iqparse(get(handles.editCarrierSpacing, 'String'), 'scalar');
carrierOffset = iqparse(get(handles.editCarrierOffset, 'String'), 'vector');
fc = iqparse(get(handles.editFc, 'String'), 'scalar');

if (length(carrierOffset) == 1 && numCarriers > 1)
    carrierOffset = carrierOffset:carrierSpacing:(carrierOffset + (numCarriers - 1) * carrierSpacing);
else
    carrierOffset = sort(carrierOffset);
end

% save some app data for the multical process
setappdata(0,'numOfCarriers', numCarriers);
setappdata(0, 'chCenterFreq', plus(carrierOffset, fc));
setappdata(0, 'chBand', (symbolRate * (1+ filterBeta)));

% Launch GUI
multiCarrierControl_GUI;


% --------------------------------------------------------------------
function menuMohawkCal_Callback(hObject, eventdata, handles)
% hObject    handle to menuMohawkCal (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
if (~isdeployed)
    mypath = fullfile(fileparts(which('iqmain')), 'U9391');
    addpath(mypath);
end
iqmohawk_gui;


% --------------------------------------------------------------------
function menuAmpDepPhase_Callback(hObject, eventdata, handles)
% hObject    handle to menuAmpDepPhase (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
% if (isfield(handles, 'adpwin') && isvalid(handles.adpwin))
%     figure(handles.adpwin.AmplitudedependendphasecorrectionUIFigure);
% else
%     handles.adpwin = iqampdepphase();
%     guidata(hObject, handles);
% end
iqampdepphase();


% --------------------------------------------------------------------
function menuUSPAVSA_Callback(hObject, eventdata, handles)
menuUSPAVSA_Action(hObject, eventdata, handles);


%---------------------------------------------------------------------
function menuUSPAVSA_Action(hObject, eventdata, handles)
% hObject    handle to menuUSPAVSA (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
% hObject    handle to menuDCAVSA (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
fc = iqparse(get(handles.editCarrierOffset, 'String'), 'vector');
if (length(fc) ~= 1)
    errordlg('This function is not supported for multi-carrier signals. Please specify a single value as a carrier offset');
    return;
end
numSamples = iqparse(get(handles.editNumSamples, 'String'), 'scalar');
oversampling = iqparse(get(handles.editOversampling, 'String'), 'scalar');
[n,d] = rat(oversampling, handles.os_resolution);
oversampling = n / d;
numSymbols = round(numSamples / oversampling);
symbolRate = iqparse(get(handles.editSymbolRate, 'String'), 'scalar');
sampleRate = iqparse(get(handles.editSampleRate , 'String'), 'scalar');
if (symbolRate < 1e9)
    errordlg('This function is only supported for symbol rates >= 1 GSym/s');
    return;
end
% avg and spb are hardcoded for now (don't ask too many questions)
avg = 6;
if (fc ~= 0) % signal on a carrier
    if (symbolRate/2 > fc)
        errordlg('Carrier Frequency must be greater than SymbolRate/2');
        return;
    end
    % samples per symbol depends on the carrier frequency
    spb = round(80 / symbolRate * fc);
else % baseband
    errordlg('M8135A only has one channel, carrier Frequency must be greater than zero!');
        return;
end
% get menu setting for clock generation 

% Calculate number of required samples (when fs,ADC is not equal to fs,DAC
% ; tbi

%%%%%%%%%%%%%%%%%%%%%%%

% calculate the number of samples that will be captured in the scope
ADCSamples = numSamples;
% rough formula for the number of seconds it takes to capture the signal on a DCA-X

vsaApp = vsafunc([], 'open');
if (isempty(vsaApp))
    return;
end
vsafunc(vsaApp, 'stop');
% just to be sure: download the waveform
% pushbuttonDownload_Callback(hObject, eventdata, handles);
% autoscale
arbConfig = loadArbConfig();
% acquire the signal from the DCA
hMsgBox = msgbox('Acquiring data from M8135A. Please wait...', 'Please wait...');
try
    [sig] = iqreadM8135A(arbConfig, sampleRate, ADCSamples);
catch ME
    % most errors are thrown inside iqreadM8135A. Turn them into dialog
    % here.
    try close(hMsgBox); catch ex; end
    errordlg(ME.message)
    return;
end
try close(hMsgBox); catch ex; end
% Check if captured waveform is correct (tbi)
if (size(sig,2) ~= 1)
    errordlg('Waveform capture from M8135A failed. Expected one trace. Please check connections');
    return;
end
sig = sig - mean(sig);
sigADC = complex(sig, zeros(size(sig)));

% make the result visible in the MATLAB workspace for further manual analysis
% assignin('base', 'fsADC', fsDCA);
assignin('base', 'sigADC', sigADC);
% configure VSA
handles.lastDownload = 'M8135A';
guidata(hObject, handles);
modTypeList = get(handles.popupmenuModType, 'String');
modTypeIdx = get(handles.popupmenuModType, 'Value');
filterList = get(handles.popupmenuFilter, 'String');
filterIdx = get(handles.popupmenuFilter, 'Value');
filterBeta = iqparse(get(handles.editFilterBeta, 'String'), 'scalar');
resultLength = iqparse(get(handles.editResultLength, 'String'), 'scalar');
filterLength = iqparse(get(handles.editFilterLength, 'String'), 'scalar');
convergence = iqparse(get(handles.editConvergence, 'String'), 'scalar');
vsaApp = vsafunc([], 'open');
if (~isempty(vsaApp))
    demodType = 'CustomIQ'; % 'DigDemod';
    hMsgBox = msgbox('Configuring VSA software. Please wait...');
    vsafunc(vsaApp, 'preset');
    vsafunc(vsaApp, 'input', 1);
    vsafunc(vsaApp, 'load', sigADC, sampleRate);
    vsafunc(vsaApp, demodType, modTypeList{modTypeIdx}, symbolRate, filterList{filterIdx}, filterBeta, resultLength);
    vsafunc(vsaApp, 'equalizer', false, filterLength, convergence, demodType);
    if (strcmp(filterList{filterIdx}, 'Gaussian'))
        spanScale = 9 * filterBeta;
    else
        spanScale = 1 + filterBeta;
    end
    vsafunc(vsaApp, 'freq', fc, symbolRate * spanScale, 51201, 'flattop', 3);
    vsafunc(vsaApp, 'trace', 4, demodType);
    vsafunc(vsaApp, 'start', 1);
    vsafunc(vsaApp, 'autoscale');
    try
        close(hMsgBox);
    catch
    end
end


% --- Executes on selection change in popupmenuDataY.
function popupmenuDataY_Callback(hObject, eventdata, handles)
% hObject    handle to popupmenuDataY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
popupmenuData_Changed(handles);


% --- Executes during object creation, after setting all properties.
function popupmenuDataY_CreateFcn(hObject, eventdata, handles)
% hObject    handle to popupmenuDataY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: popupmenu controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editDataY_Callback(hObject, eventdata, handles)
% hObject    handle to editDataY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editDataY as text
%        str2double(get(hObject,'String')) returns contents of editDataY as a double


% --- Executes during object creation, after setting all properties.
function editDataY_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editDataY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editShiftY_Callback(hObject, eventdata, handles)
% hObject    handle to editShiftY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editShiftY as text
%        str2double(get(hObject,'String')) returns contents of editShiftY as a double


% --- Executes during object creation, after setting all properties.
function editShiftY_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editShiftY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editCustomPrbs_Callback(hObject, eventdata, handles)
% hObject    handle to editCustomPrbs (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
if ~isempty(checkCustomPrbs(handles.editCustomPrbs))
    prbsChanged(handles);
end


% --- Executes during object creation, after setting all properties.
function editCustomPrbs_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editCustomPrbs (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editCustomPrbsY_Callback(hObject, eventdata, handles)
% hObject    handle to editCustomPrbsY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
if ~isempty(checkCustomPrbs(handles.editCustomPrbsY))
    prbsChanged(handles);
end


function poly = checkCustomPrbs(handle)
% check for correct format for PRBS polynomial
% return the polynomial as a vector of coefficients or [] in case of error
% set background to red in case of syntax error
poly = checkPrbs(strtrim(get(handle, 'String')));
if ~isempty(poly)
    set(handle, 'Background', 'white');
else
    set(handle, 'Background', 'red');
    errordlg('Specify PRBS polynomial in the form "7 6 0" or "x^7 + x^6 + 1" with descending coefficients');
end


function poly = checkPrbs(prbsStr)
% check for correct format for PRBS polynomial
% return the polynomial as a vector of coefficients or [] in case of error
poly = [];
% replace x by x^1 to simplify the following matches
prbsStr = regexprep(prbsStr, '\+\s*([a-zA-Z])\s*\+', '+$1^1+');
% check for e.g. "7 1 0"
if ~isempty(regexp(prbsStr, '^(?:\d+\s+)+0$', 'once'))
    poly = sscanf(prbsStr, '%d').';
    if ~issorted(poly, 2, 'descend')
        poly = [];
    end
% check for e.g. "x^7 + x + 1"
elseif ~isempty(regexp(prbsStr, '^(?:[a-zA-Z]\s*\^\s*\d+\s*\+\s*)+1$', 'once'))
    poly = str2double(regexp(prbsStr, '(\d+)', 'match'));
    poly(end) = 0;
    if ~issorted(poly, 2, 'descend')
        poly = [];
    end
end


% --- Executes during object creation, after setting all properties.
function editCustomPrbsY_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editCustomPrbsY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


% --------------------------------------------------------------------
function menuDualPolarization_Callback(hObject, eventdata, handles)
% hObject    handle to menuDualPolarization (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
dualPol = strcmp('on', get(handles.menuDualPolarization, 'Checked'));
dualPol = ~dualPol;
if dualPol
    set(handles.menuDualPolarization, 'Checked', 'on');
else
    set(handles.menuDualPolarization, 'Checked', 'off');
end
% reset the channel mapping
arbConfig = loadArbConfig();
if dualPol
    type = 'DualIQ';
else
    type = 'IQ';
end
%debugChMap('iqmod_gui: before iqchannelsetup', get(handles.pushbuttonChannelMapping, 'UserData'));
iqchannelsetup('setup', handles.pushbuttonChannelMapping, arbConfig, type);
%debugChMap('iqmod_gui: before iqchannelsetup', get(handles.pushbuttonChannelMapping, 'UserData'));
% reconfigure that GUI
popupmenuData_Changed(handles);


function editFilenameY_Callback(hObject, eventdata, handles)
% hObject    handle to editFilenameY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editFilenameY as text
%        str2double(get(hObject,'String')) returns contents of editFilenameY as a double


% --- Executes during object creation, after setting all properties.
function editFilenameY_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editFilenameY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


% --- Executes on button press in pushbuttonFilenameY.
function pushbuttonFilenameY_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonFilenameY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)


% --- Executes on button press in checkboxInvert.
function checkboxInvert_Callback(hObject, eventdata, handles)
% hObject    handle to checkboxInvert (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hint: get(hObject,'Value') returns toggle state of checkboxInvert


% --- Executes on selection change in popupmenuPrbs.
function popupmenuPrbs_Callback(hObject, eventdata, handles)
% hObject    handle to popupmenuPrbs (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
prbsChanged(handles);


% --- Executes during object creation, after setting all properties.
function popupmenuPrbs_CreateFcn(hObject, eventdata, handles)
% hObject    handle to popupmenuPrbs (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: popupmenu controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


% --- Executes on selection change in popupmenuPrbsY.
function popupmenuPrbsY_Callback(hObject, eventdata, handles)
% hObject    handle to popupmenuPrbsY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
prbsChanged(handles);


% --- Executes during object creation, after setting all properties.
function popupmenuPrbsY_CreateFcn(hObject, eventdata, handles)
% hObject    handle to popupmenuPrbsY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: popupmenu controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


% --- Executes on button press in checkboxInvertY.
function checkboxInvertY_Callback(hObject, eventdata, handles)
% hObject    handle to checkboxInvertY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hint: get(hObject,'Value') returns toggle state of checkboxInvertY



function editShift_Callback(hObject, eventdata, handles)
% hObject    handle to editShift (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editShift as text
%        str2double(get(hObject,'String')) returns contents of editShift as a double


% --- Executes during object creation, after setting all properties.
function editShift_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editShift (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


% --- Executes on button press in checkboxNLCorrection.
function checkboxNLCorrection_Callback(hObject, eventdata, handles)
% hObject    handle to checkboxNLCorrection (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hint: get(hObject,'Value') returns toggle state of checkboxNLCorrection


% --- Executes on button press in pushbuttonEditNLCorrection.
function pushbuttonEditNLCorrection_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonEditNLCorrection (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
iqsnlcorr_gui();



function editQuadErrY_Callback(hObject, eventdata, handles)
% hObject    handle to editQuadErrY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editQuadErrY as text
%        str2double(get(hObject,'String')) returns contents of editQuadErrY as a double


% --- Executes during object creation, after setting all properties.
function editQuadErrY_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editQuadErrY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editIQSkewY_Callback(hObject, eventdata, handles)
% hObject    handle to editIQSkewY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editIQSkewY as text
%        str2double(get(hObject,'String')) returns contents of editIQSkewY as a double


% --- Executes during object creation, after setting all properties.
function editIQSkewY_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editIQSkewY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editGainImbalanceY_Callback(hObject, eventdata, handles)
% hObject    handle to editGainImbalanceY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)

% Hints: get(hObject,'String') returns contents of editGainImbalanceY as text
%        str2double(get(hObject,'String')) returns contents of editGainImbalanceY as a double


% --- Executes during object creation, after setting all properties.
function editGainImbalanceY_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editGainImbalanceY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end



function editXYgainImbalance_Callback(hObject, eventdata, handles)
% hObject    handle to editXYgainImbalance (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
iqparse(handles.editXYgainImbalance, 'scalar');

% --- Executes during object creation, after setting all properties.
function editXYgainImbalance_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editXYgainImbalance (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end


% --- Executes on button press in checkboxPrbsDC.
function checkboxPrbsDC_Callback(hObject, eventdata, handles)
% hObject    handle to checkboxPrbsDC (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
prbsChanged(handles);


% --- Executes on button press in checkboxPrbsDCY.
function checkboxPrbsDCY_Callback(hObject, eventdata, handles)
% hObject    handle to checkboxPrbsDCY (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)


% --- Executes on button press in checkboxPhaseNoise.
function checkboxPhaseNoise_Callback(hObject, eventdata, handles)
% hObject    handle to checkboxPhaseNoise (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
val = get(handles.checkboxPhaseNoise, 'Value');
if val
    try
        acs = load(iqampCorrFilename());
        if acs.pnVersion ~= 1
            error('error');
        end
    catch ex
        iqphasenoise_gui();
    end
end

% --- Executes on button press in pushbuttonShowPhaseNoise.
function pushbuttonShowPhaseNoise_Callback(hObject, eventdata, handles)
% hObject    handle to pushbuttonShowPhaseNoise (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
iqphasenoise_gui();



function editXYskew_Callback(hObject, eventdata, handles)
% hObject    handle to editXYskew (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    structure with handles and user data (see GUIDATA)
iqparse(handles.editXYskew, 'scalar');


% --- Executes during object creation, after setting all properties.
function editXYskew_CreateFcn(hObject, eventdata, handles)
% hObject    handle to editXYskew (see GCBO)
% eventdata  reserved - to be defined in a future version of MATLAB
% handles    empty - handles not created until after all CreateFcns called

% Hint: edit controls usually have a white background on Windows.
%       See ISPC and COMPUTER.
if ispc && isequal(get(hObject,'BackgroundColor'), get(0,'defaultUicontrolBackgroundColor'))
    set(hObject,'BackgroundColor','white');
end
