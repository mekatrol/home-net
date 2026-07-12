using System.Text.Json.Serialization;

namespace LedSequence.Api;

public sealed record ControllerDefinition(
    OutputDefinition? Onboard,
    OutputDefinition? String1,
    OutputDefinition? String2,
    OutputDefinition? String3,
    OutputDefinition? String4);

public sealed record CreateControllerRequest(
    string Address,
    ControllerDefinition Definition);

public sealed record OutputDefinition(
    int SequenceIntervalMs,
    string Format,
    int LedCount,
    IReadOnlyList<FrameDefinition> Frames);

public sealed record FrameDefinition(
    string? Fill,
    IReadOnlyList<string>? Pixels);

public sealed record EncodedOutput(
    [property: JsonPropertyName("sequenceIntervalMs")] int SequenceIntervalMs,
    [property: JsonPropertyName("format")] string Format,
    [property: JsonPropertyName("bytesPerLed")] int BytesPerLed,
    [property: JsonPropertyName("sequences")] IReadOnlyList<string> Sequences,
    [property: JsonPropertyName("ledCount"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? LedCount);

public sealed record EncodedController(
    [property: JsonPropertyName("onboard"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] EncodedOutput? Onboard,
    [property: JsonPropertyName("string1"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] EncodedOutput? String1,
    [property: JsonPropertyName("string2"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] EncodedOutput? String2,
    [property: JsonPropertyName("string3"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] EncodedOutput? String3,
    [property: JsonPropertyName("string4"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] EncodedOutput? String4);
