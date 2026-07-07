param(
    [string]$Root = (Join-Path $PSScriptRoot "..\frontend"),
    [int]$Port = 8642
)

$Root = (Resolve-Path $Root).Path
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:$Port/")
$listener.Start()
Write-Host "Serving $Root on http://localhost:$Port/"

$mime = @{
    ".html" = "text/html"; ".js" = "application/javascript"; ".css" = "text/css";
    ".json" = "application/json"; ".png" = "image/png"; ".svg" = "image/svg+xml";
}

while ($listener.IsListening) {
    $ctx = $listener.GetContext()
    $req = $ctx.Request
    $res = $ctx.Response
    try {
        $path = [Uri]::UnescapeDataString($req.Url.AbsolutePath)
        if ($path -eq "/") { $path = "/index.html" }
        $full = Join-Path $Root ($path.TrimStart("/"))
        if (Test-Path $full -PathType Container) { $full = Join-Path $full "index.html" }
        if (Test-Path $full -PathType Leaf) {
            $ext = [IO.Path]::GetExtension($full)
            $ct = $mime[$ext]
            if (-not $ct) { $ct = "application/octet-stream" }
            $res.ContentType = $ct
            $bytes = [IO.File]::ReadAllBytes($full)
            $res.ContentLength64 = $bytes.Length
            $res.OutputStream.Write($bytes, 0, $bytes.Length)
        } else {
            $res.StatusCode = 404
        }
    } catch {
        $res.StatusCode = 500
    } finally {
        $res.OutputStream.Close()
    }
}
