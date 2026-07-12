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
