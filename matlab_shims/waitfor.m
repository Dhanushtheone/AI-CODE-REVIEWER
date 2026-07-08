function waitfor(varargin)
%WAITFOR Server-side override of the built-in waitfor.
%   Student scripts often call waitfor(fig) to keep a plot window open
%   until a human closes it interactively. On this server nobody is
%   sitting at the machine to close it, so the real waitfor would block
%   the shared MATLAB session forever. This override captures any figure
%   handle among the arguments to PNG (path set via setappdata(0,
%   'PylensCapturePath', ...) before the run) and closes it immediately,
%   so the script continues exactly as if the user had just closed the
%   window right away.
    capturePath = '';
    if isappdata(0, 'PylensCapturePath')
        capturePath = getappdata(0, 'PylensCapturePath');
    end
    for i = 1:numel(varargin)
        h = varargin{i};
        if isgraphics(h) && isvalid(h)
            if ~isempty(capturePath)
                try
                    exportgraphics(h, capturePath, 'Resolution', 150);
                catch
                end
            end
            try
                close(h);
            catch
            end
        end
    end
end
