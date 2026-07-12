using LedSequence.Api;

namespace LedSequence.Api.Tests;

public sealed class SequenceEncoderTests
{
    private readonly SequenceEncoder _encoder = new();

    [Fact]
    public void EncodeOutput_ReordersRgbColorIntoGrbWireBytes()
    {
        var definition = new OutputDefinition(
            1000,
            "grb",
            2,
            [new FrameDefinition("#00b4ff", null)]);

        var result = _encoder.EncodeOutput(definition, isOnboard: false)!;

        Assert.Equal(3, result.BytesPerLed);
        Assert.Equal(2, result.LedCount);
        Assert.Equal([180, 0, 255, 180, 0, 255], Convert.FromBase64String(result.Sequences[0]));
    }

    [Fact]
    public void EncodeOutput_RejectsFrameWithWrongPixelCount()
    {
        var definition = new OutputDefinition(
            1000,
            "rgb",
            2,
            [new FrameDefinition(null, ["#000000"])]);

        var exception = Assert.Throws<InvalidDataException>(() => _encoder.EncodeOutput(definition, isOnboard: false));

        Assert.Contains("exactly 2", exception.Message);
    }

    [Fact]
    public void EncodeOutput_OmitsLedCountForOnboardLed()
    {
        var definition = new OutputDefinition(
            250,
            "rgb",
            1,
            [new FrameDefinition("#ff80ff", null)]);

        var result = _encoder.EncodeOutput(definition, isOnboard: true)!;

        Assert.Null(result.LedCount);
        Assert.Equal([255, 128, 255], Convert.FromBase64String(result.Sequences[0]));
    }
}
