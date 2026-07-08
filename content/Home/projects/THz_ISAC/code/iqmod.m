%% IMPORTANT: If the Software includes one or more computer programs bearing a Keysight copyright notice and in source code format (“Source Files”), 
%% such Source Files are subject to the terms and conditions of the Keysight Software End-User License Agreement (“EULA”) www.Keysight.com/find/sweula and these Supplemental Terms.
%% BY USING THE SOURCE FILES, YOU AGREE TO BE BOUND BY THE TERMS AND CONDITIONS OF THE EULA INCLUDING THESE SUPPLEMENTAL TERMS. IF YOU DO NOT AGREE TO THESE TERMS AND CONDITIONS, 
%% DO NOT COPY OR DISTRIBUTE THE SOURCE FILES.
%%    1.	Additional Rights and Limitations. If Source Files are included with the Software, Keysight grants you a limited, non-exclusive license, without a right to sub-license, 
%%          to copy, modify and distribute the Source Files solely in conjunction with Keysight instruments.
%%    2.	Distribution Requirements. Any distribution of the Source Files, unmodified or modified, to an external party shall be in conjunction with distribution of your system or 
%%          product and shall be pursuant to an enforceable agreement that provides similar protections for Keysight and its suppliers as those contained in the EULA and these Supplemental Terms. 
%%    3.	General. Capitalized terms used in these Supplemental Terms and not otherwise defined herein shall have the meanings assigned to them in the EULA. To the extent that any of these 
%%          Supplemental Terms conflict with terms in the EULA, these Supplemental Terms control solely with respect to the Source Files.

function varargout = iqmod(varargin)
% Generate I/Q modulation waveform
% Parameters are passed as property/value pairs. Properties are:
% 'sampleRate' - sample rate in Hz
% 'numSymbols' - number of symbols
% 'modType' - modulation type (BPSK, QPSK, QAM16, ...) or iqConstellation object
% 'oversampling' - oversampling rate
% 'filterType' - pulse shaping filter ('Raised Cosine','Square Root Raised Cosine','Gaussian')
% 'filterNsym' - number of symbols for pulse shaping filter
% 'filterBeta' - Alpha/BT for pulse shaping filter
% 'carrierOffset' - frequency of carriers (can be a scalar or vector)
% 'magnitude' - relative magnitude (in dB) for the individual carriers
% 'newdata' - set to 1 if you want separate random bits to be generated for each carrier
% 'correction' - apply amplitude correction stored in iqampCorr()
% 'quadErr' - quadrature error in degrees
% 'plotConstellation' - to plot the constellation diagram
% 'channelMapping' - channel mapping array (format see iqdownload)
%
% If called without arguments, opens a graphical user interface to specify
% parameters
%

if (nargin == 0)
    iqmod_gui;
    return;
end
if (nargout >= 1)
    varargout{1} = [];
end
if (nargout >= 2)
    varargout{2} = [];
end
if (nargout >= 3)
    varargout{3} = [];
end
if (nargout >= 4)
    varargout{4} = [];
end
if (nargout >= 5)
    varargout{5} = [];
end
sampleRate = 4.2e9;
numSymbols = 256;
data = 'Random';
modType = 'QAM16';
oversampling = 4;
filterType = 'Root Raised Cosine';
filterNsym = 8;
filterBeta = 0.35;
filename = '';
dataContent = [];
carrierOffset = 0;
magnitude = 0;
quadErr = 0;
iqskew = 0;
gainImb = 0;
xyGainImb = 0;
xySkew = 0;
newdata = 1;
correction = 0;
snlCorrection = 0;
phasenoise = 0;
normalize = 1;
plotConstellation = 0;
threshold = [];
savefile = [];
arbConfig = [];
fct = 'display';
channelMapping = [1 0; 0 1];
hMsgBox = [];
segmNum = 1;
dataY = [];
dataContentY = [];
filenameY = [];
shift = 0;
invert = 0;
i = 1;
while (i <= nargin)
    if (ischar(varargin{i}))
        switch lower(varargin{i})
            case 'samplerate';     sampleRate = varargin{i+1};
            case 'numsymbols';     numSymbols = varargin{i+1};
            case 'modtype';        modType = varargin{i+1};
            case 'data';           data = varargin{i+1};
            case 'datacontent';    dataContent = varargin{i+1};
            case 'datay';          dataY = varargin{i+1};
            case 'datacontenty';   dataContentY = varargin{i+1};
            case 'filenamey';      filenameY = varargin{i+1};
            case 'shift';          shift = varargin{i+1};
            case 'invert';         invert = varargin{i+1};
            case 'filename';       filename = varargin{i+1};
            case 'oversampling';   oversampling = varargin{i+1};
            case 'filtertype';     filterType = varargin{i+1};
            case 'filternsym';     filterNsym = varargin{i+1};
            case 'filterbeta';     filterBeta = varargin{i+1};
            case 'carrieroffset';  carrierOffset = varargin{i+1};
            case 'magnitude';      magnitude = varargin{i+1};
            case 'quaderr';        quadErr = varargin{i+1};
            case 'iqskew';         iqskew = varargin{i+1};
            case 'gainimbalance';  gainImb = varargin{i+1};
            case 'xygainimbalance'; xyGainImb = varargin{i+1};
            case 'xyskew';         xySkew = varargin{i+1};
            case 'newdata';        newdata = varargin{i+1};
            case 'correction';     correction = varargin{i+1};
            case 'snlcorrection';  snlCorrection = varargin{i+1};
            case 'phasenoise';     phasenoise = varargin{i+1};
            case 'normalize';      normalize = varargin{i+1};
            case 'plotconstellation'; plotConstellation = varargin{i+1};
            case 'arbconfig';      arbConfig = varargin{i+1};
            case 'function';       fct = varargin{i+1};
            case 'threshold';      threshold = varargin{i+1};
            case 'savefile';       savefile = varargin{i+1};
            case 'channelmapping'; channelMapping = varargin{i+1};
            case 'hmsgbox';        hMsgBox = varargin{i+1};
			case 'segmentnumber';  segmNum = varargin{i+1};
            otherwise error(['unexpected argument: ' varargin{i}]);
        end
    else
        error('string argument expected');
    end
    i = i+2;
end

%% create a modulator object
offsetmod = 0;
iscpm = 0;
clear hmod;
if ischar(modType)
    iqCnst = iqConstellation(modType);
elseif isa(modType, 'iqConstellation')
    iqCnst = modType;
else
    error('unexpected modType: %s', class(modType));
end

% plotConstellation is no longer called, just here for legacy
if (plotConstellation)
    figure(3); clf;
    iqCnst.plot();
    return;
end

% use the same sequence every time so that results are comparable
randStream = RandStream('mt19937ar'); 
reset(randStream);

%% determine the value of numSymbols (could be reading from file)
% sym = generate_sym(numSymbols, hmod.m, randStream, data, dataContent, filename);
sym = generate_sym(numSymbols, randStream, iqCnst, data, dataY, dataContent, dataContentY, filename, filenameY, shift, invert);
numSymbols = size(sym, 1);
if (numSymbols == 0)
    return;
end

%% determine the number of samples that we need
% find rational number to approximate the oversampling
[overN, overD] = rat(oversampling);
% minimum number of samples that are necessary (must be an integer!)
numSamplesRaw = numSymbols * overN / gcd(overD, numSymbols);
% adjust number of samples to match AWG limitations
arbConfig = loadArbConfig(arbConfig);
numSamples = lcm(numSamplesRaw, arbConfig.segmentGranularity);
% make sure we have at least the minimum number of samples for this AWG
if numSamples < arbConfig.minimumSegmentSize
    numSamples = numSamples * ceil(arbConfig.minimumSegmentSize / numSamples);
end
% decide if we can keep the desired sample rate or need to re-sample
doArbResample = 0;
% If the number of samples is below this threshold we will keep the
% desired sample rate and avoid resampling. If it is higher,
% then re-sample - even if we could keep the sample rate
% but would need a very large number of samples
thresholdSamples = 1024*1024;
% new algo: if the fractional oversampling generates more than K times the
% (theoretical) minimum required number of samples, use arbitrary oversampling
osRound = ceil(oversampling);
if numSamples > osRound * numSymbols && numSamples > min(thresholdSamples, arbConfig.maximumSegmentSize)
    doArbResample = 1;
    overN = osRound;
    overD = 1;
    numSamples = overN * numSymbols;
    % make sure we have at least the minimum number of samples for this AWG
    if numSamples < arbConfig.minimumSegmentSize
        numSamples = numSamples * ceil(arbConfig.minimumSegmentSize / numSamples);
    end
    % msgbox('Waveform will be re-sampled to match AWG''s granularity requirements', 'Note', 'replace');
end

% adjust the number of symbols if necessary
newNumSymbols = round(numSamples / overN * overD);
if (numSymbols ~= newNumSymbols)
    sym = repmat(sym, ceil(newNumSymbols / numSymbols), 1);
    if size(sym, 1) > newNumSymbols
        sym(newNumSymbols+1,:) = [];
    end
    numSymbols = newNumSymbols;
end

%% determine if this a "large" waveform that will be downloaded directly
if isempty(threshold)
    if (evalin('base', 'exist(''largeDataThreshold'', ''var'') && largeDataThreshold > 0'))
        threshold = evalin('base', 'largeDataThreshold');
    else
        threshold = 8000000;
    end
end

overK = 1;
if (numSamples < threshold)
    % for large oversampling factors, perform the filtering at a lower
    % rate, then upsample. This will save calculation time
    fcs = factor(overN);
    i = 1;
    fc = 1;
    while (i <= length(fcs) && fc < 8 * overD)
        fc = fc * fcs(i);
        i = i+1;
    end
    overK = overN / fc;
    overN = overN / overK;
end

%% create a filter for pulse shaping
if (overN <= 1)  % avoid error when creating a filter when there is nothing to filter
    filterType = 'None';
end
switch (filterType)
    case 'None'
        filt.Numerator = 1;
    case 'Rectangular'
        filt.Numerator = ones(1, overN) / overN;
    case {'Root Raised Cosine' 'Square Root Raised Cosine' 'RRC'}
        filt.Numerator = rcosdesign(filterBeta, filterNsym, overN, 'sqrt');
    case {'Raised Cosine' 'RC'}
        filt.Numerator = rcosdesign(filterBeta, filterNsym, overN, 'normal');
    case 'Gaussian'
        filt.Numerator = gaussdesign(filterBeta, filterNsym, overN);
    otherwise
        error(['unknown filter type: ' filterType]);
end

%% calculate the relative magnitudes of each carrier in a multi-carrier case
if (isempty(magnitude))
    magnitude = 0;
end
if (length(magnitude) < length(carrierOffset))
    magnitude = reshape(magnitude, length(magnitude), 1);
    magnitude = repmat(magnitude, ceil(length(carrierOffset) / length(magnitude)), 1);
end

%% handle large waveforms in chunks
if (numSamples >= threshold)
    if (mod(numSamples, arbConfig.segmentGranularity) ~= 0)
        errordlg('re-sampling of large waveforms is not yet implemented');
        return;
    end
    if (length(magnitude) > 1)
        errordlg('multi-carrier in conjunction with large waveforms is not yet implemented');
        return;
    end
    if any(iqskew)
        errordlg('iqskew on large waveforms is not yet implemented');
        return;
    end
    if ~isempty(dataY)
        errordlg('dual polarization with large waveforms is not yet implemented');
        return;
    end
    fSave = [];
    if (strcmpi(fct, 'save'))
        if (~isempty(savefile))
            filterIdx = 1;
            if (~isempty(strfind(savefile, '.bin'))) %#ok<STREMP>
                filterIdx = 2;
            end
        else
            [FileName,PathName,filterIdx] = uiputfile({...
                '.csv', 'CSV file (*.csv)'; ...
                '.pbin12', '12-bit packed binary (*.pbin12)'; ...
                '.bin', 'IQBIN, 16-bit I+Q values (*.bin)'}, ...
                'Save Waveform As...');
            if isequal(FileName,0) || isequal(PathName,0)
               return;
            end
            savefile = fullfile(PathName, FileName);
        end
        fSave = fopen(savefile, 'w');
        if isempty(fSave) || fSave < 0
            errordlg(sprintf('Can''t open %s\n', savefile));
            return;
        end
    end
    if (strcmpi(fct, 'download'))
        if (numSamples > arbConfig.maximumSegmentSize)
            errordlg(['Waveform length (' num2str(numSamples) ') exceeds AWG memory size (' num2str(arbConfig.maximumSegmentSize) ')'], 'Error');
            return;
        end
    end
    % close the "Calculating waveform..." dialog box
    try close(hMsgBox); catch; end
    % currently, we only support one I/Q pair
    if (max(sum(abs(channelMapping))) > 1)
        errordlg('For large waveforms, only a single I/Q pair is supported. Please change the "Download To" to have at most one "I" and one "Q" checkbox checked');
        return;
    end
    % make an overlapsave instances from the pulse shape filter
    ovsPulseShape_I = overlapsave(filt.Numerator', overD);
    ovsPulseShape_Q = overlapsave(filt.Numerator', overD);
    % make overlapsave instances for correction filters
    ovsPerChannel_I = [];
    ovsPerChannel_Q = [];
    ovsComplex = [];
    if (correction)
        [complexCorr, perChannelCorr, ~, pidx] = iqcorrection([], [], 'chMap', channelMapping);  % get correction data
        if (~isempty(perChannelCorr))
            if (pidx(1) ~= 0)
                h = overlapsave.makeFIR(sampleRate, perChannelCorr(:,1), perChannelCorr(:,pidx(1)));
                ovsPerChannel_I = overlapsave(h);                % create filter object
                % iqcorrection will make sure that pidx(2) is ~= 0, if pidx(1) is ~= 0
                h = overlapsave.makeFIR(sampleRate, perChannelCorr(:,1), perChannelCorr(:,pidx(2)));
                ovsPerChannel_Q = overlapsave(h);                % create filter object
            end
        end
        if (~isempty(complexCorr) && size(complexCorr,1) > 2)
            h = overlapsave.makeFIR(sampleRate, complexCorr(:,1), complexCorr(:,3));
            ovsComplex = overlapsave(h);                     % create filter object
        end
    end
    % ...and create a new progress bar
    hMsgBox = iqwaitbar('Please wait...');
    try
        data = sym; %hmod.modulate(sym);
        chunkSize = round(100000 / overN);   % in symbols
        gran = arbConfig.segmentGranularity;
        cy = round(numSamples * carrierOffset(1) / sampleRate); % number of periods for carrier offset
        phi = randStream.rand(1);                               % random phase for carrier offset
        scale = 1;                                              % start with scale of 1 and increase as necessary
        oldWfm = [];      % oldWfm "remembers" the piece of the waveform that will be processed in the next iteration
        symCnt = 0;       % running count of symbols
        sampleCnt = 0;    % running count of output samples
        siCnt = 0;        % running count of input samples
        tic;
        while (sampleCnt < numSamples)
            % determine the number of symbols to be used in the next chunk
            cnt = min(chunkSize, numSymbols - symCnt);
            % upsample and scale to a value that is guaranteed to be > 1
            modData = 10 * overN * upsample(data(symCnt+1:symCnt+cnt), overN);
            % apply pulse shaping filter - must take I and Q separately because
            % the overlap and save filter does not deal with complex signals
            wfm = complex(ovsPulseShape_I.filter(real(modData)), ovsPulseShape_Q.filter(imag(modData)));
            % apply gain imbalance if requested
            if (gainImb(1) ~= 0)
                wfm = complex(real(wfm) * 10^(gainImb(1)/20), imag(wfm));
            end
            % apply quadrature error if requested
            if (quadErr(1) ~= 0)
                qe = quadErr(1) * pi / 180;
                wfm = complex(real(wfm) * cos(qe) + imag(wfm) * sin(qe), imag(wfm));
            end
            % multiply with carrier frequency (make sure we use the
            % phase that matches the position of the chunk
            if (cy ~= 0 && ~isempty(wfm))
                offset = siCnt;
                len = length(wfm);
                shiftSig = exp(1j * 2 * pi * cy * ((offset:offset+len-1)'/numSamples + phi));
                wfm = wfm .* shiftSig;
                siCnt = siCnt + len;
            end
            if phasenoise
                wfm = iqphasenoise(wfm, sampleRate);
            end
            if snlCorrection
                wfm = iqsnlcorr(wfm, [1 0]);
            end
            % apply per channel correction
            if (~isempty(ovsPerChannel_I))
                wfm = complex(ovsPerChannel_I.filter(real(wfm)), ovsPerChannel_Q.filter(imag(wfm)));
            end
            if (~isempty(ovsComplex))                  % apply complex correction
                wfm = ovsComplex.filter(wfm);
            end
            wfm = [oldWfm; wfm];                       % prepend previous waveform piece
            len = floor(length(wfm) / gran) * gran;    % use in chunks of granularity
            len = min(len, numSamples - sampleCnt);    % no more than numSamples
            oldWfm = wfm(len+1:end);                   % save last part for next loop iteration
            wfm2 = wfm(1:len);

            % check for proper scaling
            maxVal = max(max(abs(real(wfm2))),max(abs(imag(wfm2))));
            if (len > 0 && maxVal > scale)
                % check, if this is the first chunk
                if (sampleCnt == 0)
                    scale = 1.05 * maxVal;  % set new scale value with a 5% margin
                elseif (maxVal / scale <= 1)
                    % do nothing
                elseif (maxVal / scale < 1.01)   % if is less the 1% overflow, just clip the values to avoid excessive re-starts
                    % pretty complicated...  if someone can help me
                    % simplify the code, I'd appreciate it.
                    wfm2r = real(wfm2);
                    wfm2i = imag(wfm2);
                    wfm2r(wfm2r > scale) = scale;
                    wfm2i(wfm2i > scale) = scale;
                    wfm2r(wfm2r < -scale) = -scale;
                    wfm2i(wfm2i < -scale) = -scale;
                    wfm2 = complex(wfm2r, wfm2i);
                else
                    % too bad, we found a larger maxVal somewhere in the
                    % middle of the calculation --> need to start over 
                    scale = 1.05 * maxVal;  % set new scale value and add a 5% margin
                    fprintf('restarting @ sampleCnt = %d, new scale = %g\n', sampleCnt, scale);
                    sampleCnt = 0;
                    symCnt = 0;
                    oldWfm = [];
                    ovsPulseShape_I.reset();
                    ovsPulseShape_Q.reset();
                    if (~isempty(ovsPerChannel_I)); ovsPerChannel_I.reset(); end
                    if (~isempty(ovsPerChannel_Q)); ovsPerChannel_Q.reset(); end
                    if (~isempty(ovsComplex)); ovsComplex.reset(); end
                    if (strcmp(fct, 'save'))    %Wychock close the file then reopen
                        try
                            fclose(fSave);
                            fSave = fopen(savefile, 'w');
                            if (isempty(fSave))
                                errordlg(sprintf('Can''t open %s\n', savefile));
                                return;
                            end
                        catch
                        end
                    end
                    continue;
                end
            end
            if (len > 0)
                wfm2 = wfm2 / scale;
                switch (fct)
                    case 'display'
                        if (sampleCnt == 0)
                            iqplot(wfm2, sampleRate);
                        end
                    case 'download'
                        iqdownload(wfm2, sampleRate, 'channelMapping', channelMapping,...
                            'segmentLength', numSamples, 'segmentOffset', sampleCnt, 'segmentnumber', segmNum);
                    case 'save'
                        switch (filterIdx)
                            case 1  % CSV
                                for i=1:length(wfm2)
                                    fprintf(fSave, '%g,%g\n', real(wfm2(i)), imag(wfm2(i)));
                                end
                            case 2  % 12-bit packed  (2 samples -> 3 bytes)
                                if (mod(length(wfm2), 2) ~= 0)
                                    errordlg('Saving in 12-bit packed format requires an even number of samples');
                                    return;
                                end
                                a1 = real(wfm2);
                                % convert to 12 bit values
                                data1 = bitand(4095, int32(round(2047 * a1)));
                                % split into 2 rows of 12-bit values
                                data1 = reshape(data1, 2, length(data1)/2);
                                % combine into vector of 24-bit values
                                data2 = bitor(data1(1,:), bitshift(data1(2,:), 12));
                                % split into 3 rows of 8-bit values
                                data3 = uint8([bitand(data2, 255); bitand(bitshift(data2, -8), 255); bitshift(data2, -16)]);
                                % comvert to a single 8-bit vector
                                data3 = data3(1:end);
                                fwrite(fSave, data3, 'uint8');
                            case 3  % IQ BIN
                                % encode as 16 bit signed value, but leave
                                % least significant bit always zero,
                                % because it is often interpreted as a
                                % marker bit
                                data1 = int16(round(16383 * real(wfm2)) * 2)';
                                data2 = int16(round(16383 * imag(wfm2)) * 2)';
                                dataSave = [data1; data2];
                                dataSave = dataSave(1:end);
                                fwrite(fSave, dataSave, 'int16');
                        end
                    case 'none'
%                         if (sampleCnt == 0)
%                             iqdata = wfm2;
%                         end
                    otherwise 
                        error('invalid function');
                end
            end
            sampleCnt = sampleCnt + len;
            symCnt = symCnt + cnt;
            if (symCnt >= numSymbols)
                symCnt = 0;
            end
            if hMsgBox.canceling()
                break;
            end
            t = toc;
            hMsgBox.update(sampleCnt / numSamples, sprintf('Processed %d samples, %.1f%%, %.1f sec', ...
                sampleCnt, sampleCnt / numSamples * 100, t));
        end
    catch ex
        errordlg({ex.message, [ex.stack(1).name ', line ' num2str(ex.stack(1).line)]});
    end
    iqdata = [];    % don't return a partial waveform
    if (~isempty(fSave))
        try
            fclose(fSave);
        catch
        end
    end
    delete(hMsgBox);
else
    %% short waveform which fits in memory
    result = [];
    linmag = 10.^(magnitude./20);
    for i = 1:length(carrierOffset)
        if ~isempty(hMsgBox) && length(carrierOffset) > 1
            hMsgBox = msgbox(sprintf('Calculating waveform (%d / %d). Please wait...', i, length(carrierOffset)), 'Please wait...', 'replace');
        end
        if newdata || i == 1
            iqdata = iqmod_gen(sampleRate, sym, numSymbols, iqCnst, overN, overK, overD, filt, quadErr, iqskew, gainImb, xyGainImb, xySkew, offsetmod, iscpm, randStream, data, dataY, dataContent, dataContentY, filename, filenameY, shift, invert);
        end
        len = length(iqdata);
        % calculate shift frequency
        cy = round(len * carrierOffset(i) / sampleRate);
        shiftSig = exp(1j * 2 * pi * cy * (linspace(0, 1 - 1/len, len).' + randStream.rand(1)));
        if (isempty(result))
            result = linmag(i) * (iqdata .* shiftSig);
        else
            result = result + linmag(i) * (iqdata .* shiftSig);
        end
    end
    iqdata = result;

    %% re-sample, if needed
    if doArbResample
        dataRate = sampleRate / oversampling;
        playtime = numSymbols / dataRate;
        lenApprox = playtime * sampleRate;
        newLenUpper = ceil(lenApprox / arbConfig.segmentGranularity) * arbConfig.segmentGranularity;
        newLenLower = floor(lenApprox / arbConfig.segmentGranularity) * arbConfig.segmentGranularity;
        sampleRateUpper = newLenUpper / playtime;
        sampleRateLower = newLenLower / playtime;
        %
        % If the sample rate is out of range, I should have used higher
        % oversampling ratio to start with. For now, I fix it by repeating
        % the data pattern until I get into the valid range of sample
        % rates.
        % Since the interval between upper and lower gets smaller on every
        % iteration, we should eventually find a solution
        % Note, that arbConfig.minimumSampleRate and maximumSampleRate can
        % be vectors - hence the complicated comparison
        %
        k = 1; % repeat waveform k times until we find a sample rate that is within the valid range
        while isempty(find(sampleRateUpper >= arbConfig.minimumSampleRate & sampleRateUpper <= arbConfig.maximumSampleRate, 1)) && ...
              isempty(find(sampleRateLower >= arbConfig.minimumSampleRate & sampleRateLower <= arbConfig.maximumSampleRate, 1))
            k = k + 1;
            newLenUpper = ceil(k * lenApprox / arbConfig.segmentGranularity) * arbConfig.segmentGranularity;
            newLenLower = floor(k * lenApprox / arbConfig.segmentGranularity) * arbConfig.segmentGranularity;
            sampleRateUpper = newLenUpper / playtime / k;
            sampleRateLower = newLenLower / playtime / k;
            if k > 30  % avoid an endless loop, but theoretically, this should never happen
                break;
            end
        end
        % repeat the waveform if needed
        if k > 1
            iqdata = repmat(iqdata, k, 1);
        end
        if ~isempty(find(sampleRateUpper >= arbConfig.minimumSampleRate & sampleRateUpper <= arbConfig.maximumSampleRate, 1)) 
            sampleRate = sampleRateUpper;
            newLen = newLenUpper;
        elseif ~isempty(find(sampleRateLower >= arbConfig.minimumSampleRate & sampleRateLower <= arbConfig.maximumSampleRate, 1))
            sampleRate = sampleRateLower;
            newLen = newLenLower;
        else
            errordlg('internal error: could not find a sample rate in the valid range');
            error('internal error: could not find a sample rate in the valid range');
        end
        % finally, resample to the new length
        iqdata = iqresample(iqdata, newLen);
    end

    % make sure we have a column vector
    assert(size(iqdata, 2) <= 2);
    
    %% apply freq/phase response correction if necessary
    if phasenoise
        iqdata = iqphasenoise(iqdata, sampleRate);
    end
    if snlCorrection
        [iqdata, channelMapping] = iqsnlcorr(iqdata, channelMapping);
    end
    if (correction)
        nowarning = strcmp(fct, 'clock');   % don't complain about missing corrections when downloading the clock signal
        [iqdata, channelMapping] = iqcorrection(iqdata, sampleRate, 'chMap', channelMapping, 'normalize', normalize, 'nowarning', nowarning);
    end

    %% normalize the output (X and Y together!!)
    if (normalize)
        scale = max(max(max(abs(real(iqdata))), max(abs(imag(iqdata)))));
        iqdata = iqdata / scale;
    end
end

delete(randStream);
if (nargout >= 1)
    varargout{1} = iqdata;
end
if (nargout >= 2)
    varargout{2} = sampleRate;
end
if (nargout >= 3)
    varargout{3} = numSymbols;
end
if (nargout >= 4)
    varargout{4} = numSamples;
end
if (nargout >= 5)
    varargout{5} = channelMapping;
end
end


%% generate a modulated signal
function iqdata = iqmod_gen(fs, sym, numSymbols, format, overN, overK, overD, filt, quadErr, iqskew, gainImb, xyGainImb, xySkew, offsetmod, iscpm, randStream, data, dataY, dataContent, dataContentY, filename, filenameY, shift, invert)
if (ischar(data) && strcmpi(data, 'random'))
    sym = generate_sym(numSymbols, randStream, format, data, dataY, dataContent, dataContentY, filename, filenameY, shift, invert);
end
if (iscpm ~= 0)   % no built-in function for CPM modulation
    % modulate_cpm returns a PHASE vector, not IQ. For CPM, we need to run
    % the phase through the pulse shaping filter
    rawIQ = modulate_cpm(sym, overN);
    phOffset = rawIQ(end);   % correct for N * 360 deg phase offset
else
    rawIQ = upsample(sym, overN);
    phOffset = 0;
end
len = size(rawIQ, 1);
nfilt = length(filt.Numerator);
% apply the filter to the raw signal with some wrap-around to avoid glitches
wrappedIQ = [rawIQ(end-mod(nfilt,len)+1:end,:)-phOffset; repmat(rawIQ, floor(nfilt/len)+1, 1)];
tmp = fftfilt(filt.Numerator, wrappedIQ);
iqdata = tmp(nfilt+1:end, :);
% for CPM modulation, we now convert phase into I/Q
if (iscpm ~= 0)
    iqdata = exp(1j*real(iqdata));
end
% if oversampling was a fraction, downsample by the denominator
if (overD ~= 1)
    iqdata = downsample(iqdata, overD);
end
% if low oversampling was used, interpolate now
if (overK ~= 1)
    iqdata = interpft(iqdata, overK * length(iqdata));
end
% for OQPSK, shift Q by 1 symbol
if (offsetmod)
    iqdata = iqdelay(iqdata, fs, 1/2 * (overN * overK / (overD * fs)));
end
%----- apply amplitude-dependent phase correction
% pow = abs(iqdata).^2;
% pow = pow / max(pow);
% pow = pow .^ 1.0;
% phi = 0.35 .* pow;
% gain = 1 + (0.2 .* pow);
% iqdata = iqdata .* gain .* exp(1i*phi);
%-----
% apply quadrature error:  I' = I*cos(phi)+Q*sin(phi) and  Q' = Q
[n, m] = size(iqdata);
assert(n > m, 'expect column data');
if any(quadErr)
    quadErr = fixlength(quadErr, m);
    qe = repmat(exp(1j * quadErr * pi / 180), n, 1);
    iqdata = complex(real(iqdata .* qe), imag(iqdata));
end
% apply skew:  I' = delay(I) and  Q' = Q
if any(iqskew)
    iqskew = fixlength(iqskew, m);
    iqdata = iqdelay(iqdata, fs, iqskew);
end
% apply gain imbalance:  I' = gain(I) and  Q' = Q
if any(gainImb)
    gi = repmat(10.^(fixlength(gainImb, m) / 20), n, 1);
    iqdata = complex(real(iqdata) .* gi, imag(iqdata));
end
if xyGainImb
    iqdata(:,1) = iqdata(:,1) * 10^(xyGainImb/20);
end
if xySkew
    iqdata(:,1) = complex(iqdelay(real(iqdata(:,1)), fs, xySkew), iqdelay(imag(iqdata(:,1)), fs, xySkew));
end
end


function x = fixlength(x, len)
% make a vector with <len> elements by duplicating or cutting <x> as
% necessary
x = reshape(x, 1, numel(x));
x = repmat(x, 1, ceil(len / length(x)));
x = x(1:len);
end


%% generate symbols 
function sym = generate_sym(numSymbols, randStream, format, dataType, dataTypeY, dataContent, dataContentY, filename, filenameY, shift, invert)
sym = [];
try
    if strcmpi(dataType, 'Symbols from file')
        dataType = ['filesymbolnumbers ' filename];
    elseif strcmpi(dataType, 'Bits from file')
        dataType = ['filebits ' filename];
    end
    maxLen = 100000; % make sure we don't iterate too often
    dataGenX = iqstepDataGen(dataType, dataContent, numSymbols, format, shift(1), invert(1), maxLen);
    sym = dataGenX.step(numSymbols);

    if ~isempty(dataTypeY)
        if strcmpi(dataTypeY, 'Symbols from file')
            dataTypeY = ['filesymbolnumbers ' filenameY];
        elseif strcmpi(dataTypeY, 'Bits from file')
            dataTypeY = ['filebits ' filenameY];
        end
        dataGenY = iqstepDataGen(dataTypeY, dataContentY, numSymbols, format, shift(2), invert(2), maxLen);
        sym = [sym dataGenY.step(numSymbols)];
    end
catch ex
    errordlg({ex.message, [ex.stack(1).name ', line ' num2str(ex.stack(1).line)]});
end
end

% function sym = generate_sym(numSymbols, k, randStream, dataType, dataContent, filename)
% sym = [];
% b = floor(log2(k));     % number of bits per symbol (just powers of 2 for now)
% numBits = b * numSymbols;
% if (ischar(data))
%     if (~isempty(strfind(data, 'from file')))
%         data = regexprep(data, '(.*) from file', 'User defined $1');
%         try
%             f = fopen(filename, 'r');
%             dataContent = fscanf(f, '%d');
%             if (isempty(dataContent) || length(dataContent) == 1)
%                 errordlg('File format error. Expected integers separated by spaces or newlines');
%             end
%             fclose(f);
%         catch ex
%             fclose(f);
%             dataContent = zeros(numBits, 1);
%             errordlg(ex.message);
%         end
%     end
%     % legacy: clock = dataRate/2 pattern
%     if (strcmpi(data, 'clock'))
%         data = 'clock2';
%     end
%     if strncmpi(data, 'prbs', 4) && ~strncmpi(data, 'prbs2^', 6)
%         poly = checkPrbs(strtrim(data(5:end)));
%         h = comm.PNSequence('Polynomial', poly, 'SamplesPerFrame', numBits, 'InitialConditions', [zeros(1, poly(1)-1) 1]);
%         data = h.step();
%     else
%     switch(lower(data))
%         case {'clock2' 'clock3' 'clock4' 'clock5' 'clock6' 'clock7' 'clock8' 'clock16'}
%             div = str2double(data(6:end));
%             if (mod(numSymbols, div) ~= 0)
%                 warndlg(sprintf('Number of symbols is not divisible by %d - clock pattern will not be periodic', div));
%             end
%             sym = repmat([zeros(1,floor(div/2)) (k-1)*ones(1,ceil(div/2))], 1, ceil(numSymbols / div));
%         case 'clockonce'
%             sym = [zeros(1,floor(numSymbols/2)) (k-1)*ones(1,numSymbols-floor(numSymbols/2))];
%         case 'counter'
%             if (mod(numSymbols, k) ~= 0)
%                 warndlg(sprintf('Number of symbols is not divisible by %d - counter pattern will not be periodic', k));
%             end
%             sym = repmat(linspace(0, k-1, k), 1, ceil(numSymbols / k));
%         case 'random'
%             sym = floor(randStream.rand(1,numSymbols) * k);
%         case 'prbs2^7-1'
%             h = comm.PNSequence('Polynomial', 'z^7 + z^6 + 1', 'SamplesPerFrame', numBits, 'InitialConditions', [0 0 0 0 0 0 1]);
%             data = 1 - flipud(h.step())';
% %             h = commsrc.pn('GenPoly', [7 6 0], 'NumBitsOut', numBits);
% %             data = 1 - flipud(h.generate())';
%         case 'prbs2^9-1'
%             h = comm.PNSequence('Polynomial', 'z^9 + z^5 + 1', 'SamplesPerFrame', numBits, 'InitialConditions', [0 0 0 0 0 0 0 0 1]);
%             data = 1 - flipud(h.step())';
% %             h = commsrc.pn('GenPoly', [9 5 0], 'NumBitsOut', numBits);
% %             data = 1 - flipud(h.generate())';
%         case 'prbs2^10-1'
%             h = comm.PNSequence('Polynomial', 'z^10 + z^7 + 1', 'SamplesPerFrame', numBits, 'InitialConditions', [0 0 0 0 0 0 0 0 0 1]);
%             data = 1 - flipud(h.step())';
% %             h = commsrc.pn('GenPoly', [10 7 0], 'NumBitsOut', numBits);
% %             data = 1 - flipud(h.generate())';
%         case 'prbs2^11-1'
%             h = comm.PNSequence('Polynomial', 'z^11 + z^9 + 1', 'SamplesPerFrame', numBits, 'InitialConditions', [0 0 0 0 0 0 0 0 0 0 1]);
%             data = 1 - flipud(h.step())';
% %             h = commsrc.pn('GenPoly', [11 9 0], 'NumBitsOut', numBits);
% %             data = 1 - flipud(h.generate())';
%         case 'prbs2^15-1'
%             h = comm.PNSequence('Polynomial', 'z^15 + z^14 + 1', 'SamplesPerFrame', numBits, 'InitialConditions', [0 0 0 0 0 0 0 0 0 0 0 0 0 0 1]);
%             data = 1 - flipud(h.step())';
% %             h = commsrc.pn('GenPoly', [15 14 0], 'NumBitsOut', numBits);
% %             data = 1 - flipud(h.generate())';
%         case 'user defined symbols'
%             numSymbols = length(dataContent);
%             dataContent = round(dataContent);
%             if (min(dataContent) < 0 || max(dataContent) >= k)
%                 dataContent(dataContent < 0) = 0;
%                 dataContent(dataContent >= k) = k - 1;
%                 errordlg(sprintf('User defined symbols must be in the range 0 to %d', k-1));
%             end
%             sym = reshape(dataContent, 1, numSymbols);
%         case 'user defined bits'
%             numBits = length(dataContent);
%             dataContent = round(dataContent);
%             if (min(dataContent) < 0 || max(dataContent) > 1)
%                 dataContent(dataContent < 0) = 0;
%                 dataContent(dataContent > 1) = 1;
%                 errordlg('User defined bits must use values 0 and 1');
%             end
%             if (mod(numBits, b) ~= 0)
%                 errordlg(sprintf('Number of bits must be a multiple of %d', b));
%                 numBits = floor(numBits / b) * b;
%                 dataContent = dataContent(1:numBits);
%             end
%             numSymbols = numBits / b;
%             data = reshape(dataContent, numBits, 1);
%         otherwise
%             errordlg(['undefined data pattern: ' data]);
%     end
%     end
% elseif (isvector(data))     % legacy: data can be a vector of bits
%     numBits = length(data);
%     % make sure the data is in the correct format
%     data = reshape(data, numBits, 1);
% else
%     error('data must be a string with a predefined data pattern or a vector of bits');
% end
% if (isempty(sym))
%     if bitshift(1,b) ~= k
%         warndlg(sprintf(['The number of constellation states is not a power of two. ' ...
%         'Only %d out of %d states will be used. Try data type "Random" to use all constellation states'], bitshift(1,b), k));
%     end
%     % convert from numBits of [0..1] to numSymbols of [0..k-1]
%     weight = repmat(fliplr(2.^(0:b-1))', 1, numSymbols);
%     data = reshape(data, b, numSymbols);
%     sym = sum(weight .* data, 1);
% end
% assignin('base', 'sym', sym.');
% end
% 
% 
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
end


function phase = modulate_cpm(sym, os)
t = (1:os)/os;
pht = zeros(length(t), 4);
% 4 phase trajectories, depending on previous and current bit
pht(:,1) = -t;
pht(:,2) = -sin(pi*t)/pi;
pht(:,3) = sin(pi*t)/pi;
pht(:,4) = t;
phaseOffset = [-1 0 0 1];
numBits = length(sym);
res = zeros(os, numBits);
flag = sym(numBits);
phMemory = 0;
for k=1:numBits
    % index into array of phase trajectories
    idx = 2*flag + sym(k) + 1;
    flag = sym(k);
    res(:,k) = phMemory + pht(:,idx);
    phMemory = phMemory + phaseOffset(idx);
end 
phase = res(1:end) * pi;
%iq = exp(j*phase);
%n = 100;
%figure(21); plot([res(end-n+1:end) res(1:n)], '.-');
%figure(22); plot([[real(iq(end-n+1:end))' imag(iq(end-n+1:end))']; [real(iq(1:n))' imag(iq(1:n))']], '.-');
end
