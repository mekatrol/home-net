using System.Globalization;

namespace LedSequence.Api;

public sealed class SequenceEncoder
{
    public EncodedController EncodeController(ControllerDefinition definition) => new(
        EncodeOutput(definition.Onboard, isOnboard: true),
        EncodeOutput(definition.String1, isOnboard: false),
        EncodeOutput(definition.String2, isOnboard: false),
        EncodeOutput(definition.String3, isOnboard: false),
        EncodeOutput(definition.String4, isOnboard: false));

    public EncodedOutput? EncodeOutput(OutputDefinition? definition, bool isOnboard)
    {
        if (definition is null)
        {
            return null;
        }

        if (definition.SequenceIntervalMs <= 0)
        {
            throw new InvalidDataException("sequenceIntervalMs must be positive.");
        }

        var format = definition.Format.ToLowerInvariant();
        ValidateFormat(format, isOnboard);
        var ledCount = isOnboard ? 1 : definition.LedCount;
        if (ledCount is < 1 or > 2048)
        {
            throw new InvalidDataException("ledCount must be from 1 through 2048.");
        }

        if (definition.Frames.Count > 100)
        {
            throw new InvalidDataException("An output cannot contain more than 100 frames.");
        }

        var encodedFrames = definition.Frames
            .Select(frame => Convert.ToBase64String(EncodeFrame(frame, format, ledCount)))
            .ToArray();

        return new EncodedOutput(
            definition.SequenceIntervalMs,
            format,
            format.Length,
            encodedFrames,
            isOnboard ? null : ledCount);
    }

    private static byte[] EncodeFrame(FrameDefinition frame, string format, int ledCount)
    {
        IReadOnlyList<string> pixels;
        if (frame.Pixels is not null)
        {
            if (frame.Fill is not null)
            {
                throw new InvalidDataException("A frame cannot contain both fill and pixels.");
            }

            if (frame.Pixels.Count != ledCount)
            {
                throw new InvalidDataException($"A pixel frame must contain exactly {ledCount} colors.");
            }

            pixels = frame.Pixels;
        }
        else if (frame.Fill is not null)
        {
            pixels = Enumerable.Repeat(frame.Fill, ledCount).ToArray();
        }
        else
        {
            throw new InvalidDataException("A frame must contain either fill or pixels.");
        }

        var output = new byte[ledCount * format.Length];
        for (var pixelIndex = 0; pixelIndex < pixels.Count; pixelIndex++)
        {
            var channels = ParseColor(pixels[pixelIndex], format.Length == 4);
            for (var channelIndex = 0; channelIndex < format.Length; channelIndex++)
            {
                output[pixelIndex * format.Length + channelIndex] = channels[format[channelIndex]];
            }
        }

        return output;
    }

    private static Dictionary<char, byte> ParseColor(string value, bool includesWhite)
    {
        var expectedLength = includesWhite ? 9 : 7;
        if (value.Length != expectedLength || value[0] != '#')
        {
            throw new InvalidDataException(includesWhite
                ? "RGBW colors must use #RRGGBBWW notation."
                : "RGB colors must use #RRGGBB notation.");
        }

        byte ParseChannel(int offset)
        {
            if (!byte.TryParse(value.AsSpan(offset, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var channel))
            {
                throw new InvalidDataException($"'{value}' is not a valid hexadecimal color.");
            }
            return channel;
        }

        return new Dictionary<char, byte>
        {
            ['r'] = ParseChannel(1),
            ['g'] = ParseChannel(3),
            ['b'] = ParseChannel(5),
            ['w'] = includesWhite ? ParseChannel(7) : (byte)0,
        };
    }

    private static void ValidateFormat(string format, bool isOnboard)
    {
        var expectedChannels = format.Length == 3 ? "rgb" : format.Length == 4 ? "rgbw" : string.Empty;
        if (expectedChannels.Length == 0 || format.Order().SequenceEqual(expectedChannels.Order()) is false)
        {
            throw new InvalidDataException("format must contain RGB once each, with optional W.");
        }

        if (isOnboard && format.Length != 3)
        {
            throw new InvalidDataException("The onboard LED must use a three-channel RGB format.");
        }
    }
}
