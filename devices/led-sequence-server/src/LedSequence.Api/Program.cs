using System.Net;
using LedSequence.Api;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddSingleton<SequenceEncoder>();
builder.Services.AddSingleton<ControllerDefinitionStore>();

builder.WebHost.ConfigureKestrel(serverOptions =>
{
    // Listens on all local IP addresses on port 5050
    serverOptions.Listen(IPAddress.Any, 5050);
});

var app = builder.Build();

app.UseDefaultFiles();
app.UseStaticFiles();

app.MapGet("/api/controllers", async (ControllerDefinitionStore store, CancellationToken cancellationToken) =>
    Results.Ok(await store.LoadAllAsync(cancellationToken)));

app.MapPost("/api/controllers", async (
    CreateControllerRequest request,
    ControllerDefinitionStore store,
    SequenceEncoder encoder,
    CancellationToken cancellationToken) =>
{
    if (!IPAddress.TryParse(request.Address, out _))
    {
        return Results.BadRequest(new { error = "A valid controller IP address is required." });
    }

    try
    {
        encoder.EncodeController(request.Definition);
    }
    catch (InvalidDataException exception)
    {
        return Results.BadRequest(new { error = exception.Message });
    }

    return await store.AddAsync(request.Address, request.Definition, cancellationToken)
        ? Results.Created($"/api/controllers/{request.Address}", request.Definition)
        : Results.Conflict(new { error = $"A controller already exists for {request.Address}." });
});

app.MapPut("/api/controllers/{controllerIp}", async (
    string controllerIp,
    ControllerDefinition definition,
    ControllerDefinitionStore store,
    SequenceEncoder encoder,
    CancellationToken cancellationToken) =>
{
    if (!IPAddress.TryParse(controllerIp, out _))
    {
        return Results.BadRequest(new { error = "A valid controller IP address is required." });
    }

    try
    {
        encoder.EncodeController(definition);
    }
    catch (InvalidDataException exception)
    {
        return Results.BadRequest(new { error = exception.Message });
    }

    return await store.UpdateAsync(controllerIp, definition, cancellationToken)
        ? Results.Ok(definition)
        : Results.NotFound(new { error = $"No controller exists for {controllerIp}." });
});

app.MapDelete("/api/controllers/{controllerIp}", async (
    string controllerIp,
    ControllerDefinitionStore store,
    CancellationToken cancellationToken) =>
    await store.DeleteAsync(controllerIp, cancellationToken)
        ? Results.NoContent()
        : Results.NotFound(new { error = $"No controller exists for {controllerIp}." }));

app.MapGet("/favicon.ico", () => Results.NoContent());

app.MapGet("/{controllerIp}", async (
    string controllerIp,
    ControllerDefinitionStore store,
    SequenceEncoder encoder,
    CancellationToken cancellationToken) =>
{
    if (!IPAddress.TryParse(controllerIp, out _))
    {
        return Results.BadRequest(new { error = "The route must contain a valid controller IP address." });
    }

    var definition = await store.FindAsync(controllerIp, cancellationToken);
    return definition is null
        ? Results.NotFound(new { error = $"No sequence configuration exists for {controllerIp}." })
        : Results.Ok(encoder.EncodeController(definition));
});

app.MapFallbackToFile("index.html");
app.Run();

public partial class Program;
