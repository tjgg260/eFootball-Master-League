using System.Net.WebSockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace ML.Ingest;

/// <summary>
/// Minimal obs-websocket v5 client (BCL only): identify (with optional challenge auth), then
/// StartRecord / StopRecord. Used to bookend every played match with a recording the
/// <see cref="VideoAnalyzer"/> can mine afterwards. Every call is best-effort: if OBS isn't
/// running or the socket is refused, the caller gets false and the matchday carries on.
/// </summary>
public sealed class ObsRecorder : IAsyncDisposable
{
    private readonly Uri _url;
    private readonly string _password;
    private ClientWebSocket? _ws;
    private int _nextId = 1;

    public ObsRecorder(string url = "ws://127.0.0.1:4455", string password = "")
    {
        _url = new Uri(url);
        _password = password;
    }

    /// <summary>Connect + identify. False (never a throw) when OBS is not reachable.</summary>
    public async Task<bool> ConnectAsync(CancellationToken ct = default)
    {
        try
        {
            _ws = new ClientWebSocket();
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
            timeout.CancelAfter(TimeSpan.FromSeconds(4));
            await _ws.ConnectAsync(_url, timeout.Token);

            // Hello (op 0) -> Identify (op 1) -> Identified (op 2)
            var hello = await ReceiveAsync(timeout.Token);
            string? auth = null;
            if (hello.TryGetProperty("d", out var d) &&
                d.TryGetProperty("authentication", out var a))
            {
                var challenge = a.GetProperty("challenge").GetString()!;
                var salt = a.GetProperty("salt").GetString()!;
                var secret = Convert.ToBase64String(
                    SHA256.HashData(Encoding.UTF8.GetBytes(_password + salt)));
                auth = Convert.ToBase64String(
                    SHA256.HashData(Encoding.UTF8.GetBytes(secret + challenge)));
            }
            var identify = new Dictionary<string, object?>
            {
                ["op"] = 1,
                ["d"] = new Dictionary<string, object?>
                {
                    ["rpcVersion"] = 1,
                    ["authentication"] = auth,
                    ["eventSubscriptions"] = 0,
                },
            };
            await SendAsync(identify, timeout.Token);
            var identified = await ReceiveAsync(timeout.Token);
            return identified.TryGetProperty("op", out var op) && op.GetInt32() == 2;
        }
        catch
        {
            _ws?.Dispose();
            _ws = null;
            return false;
        }
    }

    public Task<bool> StartRecordingAsync(CancellationToken ct = default) =>
        RequestAsync("StartRecord", null, ct);

    /// <summary>Stops the recording. Returns the output path OBS reports, or null.</summary>
    public async Task<string?> StopRecordingAsync(CancellationToken ct = default)
    {
        var resp = await RequestRawAsync("StopRecord", null, ct);
        if (resp is null) return null;
        try
        {
            return resp.Value.GetProperty("d").GetProperty("responseData")
                .GetProperty("outputPath").GetString();
        }
        catch
        {
            return null;
        }
    }

    public async Task<bool> IsRecordingAsync(CancellationToken ct = default)
    {
        var resp = await RequestRawAsync("GetRecordStatus", null, ct);
        if (resp is null) return false;
        try
        {
            return resp.Value.GetProperty("d").GetProperty("responseData")
                .GetProperty("outputActive").GetBoolean();
        }
        catch
        {
            return false;
        }
    }

    private async Task<bool> RequestAsync(
        string type, Dictionary<string, object?>? data, CancellationToken ct)
    {
        var resp = await RequestRawAsync(type, data, ct);
        if (resp is null) return false;
        try
        {
            return resp.Value.GetProperty("d").GetProperty("requestStatus")
                .GetProperty("result").GetBoolean();
        }
        catch
        {
            return false;
        }
    }

    private async Task<JsonElement?> RequestRawAsync(
        string type, Dictionary<string, object?>? data, CancellationToken ct)
    {
        if (_ws is not { State: WebSocketState.Open }) return null;
        try
        {
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
            timeout.CancelAfter(TimeSpan.FromSeconds(6));
            var id = $"ml-{_nextId++}";
            await SendAsync(new Dictionary<string, object?>
            {
                ["op"] = 6,
                ["d"] = new Dictionary<string, object?>
                {
                    ["requestType"] = type,
                    ["requestId"] = id,
                    ["requestData"] = data,
                },
            }, timeout.Token);
            // Read frames until our RequestResponse (op 7) arrives.
            for (var i = 0; i < 12; i++)
            {
                var msg = await ReceiveAsync(timeout.Token);
                if (msg.TryGetProperty("op", out var op) && op.GetInt32() == 7 &&
                    msg.GetProperty("d").GetProperty("requestId").GetString() == id)
                {
                    return msg;
                }
            }
            return null;
        }
        catch
        {
            return null;
        }
    }

    private Task SendAsync(object payload, CancellationToken ct)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(payload,
            new JsonSerializerOptions { DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull });
        return _ws!.SendAsync(bytes, WebSocketMessageType.Text, true, ct);
    }

    private async Task<JsonElement> ReceiveAsync(CancellationToken ct)
    {
        var buf = new byte[1 << 16];
        using var ms = new MemoryStream();
        WebSocketReceiveResult r;
        do
        {
            r = await _ws!.ReceiveAsync(buf, ct);
            ms.Write(buf, 0, r.Count);
        } while (!r.EndOfMessage);
        return JsonDocument.Parse(ms.ToArray()).RootElement;
    }

    public async ValueTask DisposeAsync()
    {
        if (_ws is { State: WebSocketState.Open })
        {
            try
            {
                await _ws.CloseAsync(WebSocketCloseStatus.NormalClosure, "", CancellationToken.None);
            }
            catch { /* closing is best-effort */ }
        }
        _ws?.Dispose();
    }
}
