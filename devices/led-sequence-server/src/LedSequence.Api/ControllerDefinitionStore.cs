using System.Text.Json;

namespace LedSequence.Api;

public sealed class ControllerDefinitionStore(IConfiguration configuration, IWebHostEnvironment environment)
{
    private readonly SemaphoreSlim _writeLock = new(1, 1);
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

    public async Task<bool> AddAsync(
        string controllerIp,
        ControllerDefinition definition,
        CancellationToken cancellationToken)
    {
        await _writeLock.WaitAsync(cancellationToken);
        try
        {
            var definitions = new Dictionary<string, ControllerDefinition>(await LoadAllAsync(cancellationToken));
            if (!definitions.TryAdd(controllerIp, definition))
            {
                return false;
            }

            await SaveAllAsync(definitions, cancellationToken);
            return true;
        }
        finally
        {
            _writeLock.Release();
        }
    }

    public async Task<bool> UpdateAsync(
        string controllerIp,
        ControllerDefinition definition,
        CancellationToken cancellationToken)
    {
        await _writeLock.WaitAsync(cancellationToken);
        try
        {
            var definitions = new Dictionary<string, ControllerDefinition>(await LoadAllAsync(cancellationToken));
            if (!definitions.ContainsKey(controllerIp))
            {
                return false;
            }

            definitions[controllerIp] = definition;
            await SaveAllAsync(definitions, cancellationToken);
            return true;
        }
        finally
        {
            _writeLock.Release();
        }
    }

    public async Task<bool> DeleteAsync(string controllerIp, CancellationToken cancellationToken)
    {
        await _writeLock.WaitAsync(cancellationToken);
        try
        {
            var definitions = new Dictionary<string, ControllerDefinition>(await LoadAllAsync(cancellationToken));
            if (!definitions.Remove(controllerIp))
            {
                return false;
            }

            await SaveAllAsync(definitions, cancellationToken);
            return true;
        }
        finally
        {
            _writeLock.Release();
        }
    }

    private async Task SaveAllAsync(
        IReadOnlyDictionary<string, ControllerDefinition> definitions,
        CancellationToken cancellationToken)
    {
        var directory = Path.GetDirectoryName(_dataPath);
        if (directory is not null)
        {
            Directory.CreateDirectory(directory);
        }

        var temporaryPath = $"{_dataPath}.tmp";
        await using (var stream = File.Create(temporaryPath))
        {
            await JsonSerializer.SerializeAsync(stream, definitions, SerializerOptions, cancellationToken);
        }

        File.Move(temporaryPath, _dataPath, true);
    }
}
