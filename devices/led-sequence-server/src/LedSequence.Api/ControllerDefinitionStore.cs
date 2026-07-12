using System.Text.Json;

namespace LedSequence.Api;

public sealed class ControllerDefinitionStore(IConfiguration configuration, IWebHostEnvironment environment)
{
    private static readonly JsonSerializerOptions SerializerOptions = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = true,
        WriteIndented = true,
    };

    private readonly string _dataPath = Path.GetFullPath(
        configuration["SequenceDataPath"] ?? Path.Combine(environment.ContentRootPath, "data", "controllers.json"));

    public async Task<IReadOnlyDictionary<string, ControllerDefinition>> LoadAllAsync(CancellationToken cancellationToken)
    {
        await using var stream = File.OpenRead(_dataPath);
        return await JsonSerializer.DeserializeAsync<Dictionary<string, ControllerDefinition>>(
            stream,
            SerializerOptions,
            cancellationToken) ?? new Dictionary<string, ControllerDefinition>();
    }

    public async Task<ControllerDefinition?> FindAsync(string controllerIp, CancellationToken cancellationToken)
    {
        var definitions = await LoadAllAsync(cancellationToken);
        return definitions.GetValueOrDefault(controllerIp);
    }
}
