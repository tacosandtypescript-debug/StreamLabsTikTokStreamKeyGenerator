# Instalador de una línea para Windows.
#
#   irm https://raw.githubusercontent.com/tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator/main/install.ps1 | iex
#
# Descarga la última release, verifica su checksum, la instala en tu carpeta de
# usuario y crea los accesos directos. No necesita permisos de administrador.
#
# Para desinstalar: borra la carpeta de instalación y los accesos directos
# (la ruta exacta se imprime al terminar).

[CmdletBinding()]
param(
    [string]$Version = "latest",
    [switch]$NoShortcut,
    [switch]$Quiet,
    [switch]$AllowUnverified
)

$ErrorActionPreference = "Stop"
$Repo = "tacosandtypescript-debug/StreamLabsTikTokStreamKeyGenerator"
$AppName = "StreamLabsTikTokStreamKeyGenerator"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\$AppName"

function Write-Step([string]$Message) {
    if (-not $Quiet) { Write-Host "==> $Message" -ForegroundColor Cyan }
}

Write-Host ""
Write-Host "  StreamLabs TikTok Stream Key Generator - instalador" -ForegroundColor White
Write-Host "  ------------------------------------------------" -ForegroundColor DarkGray

# ---------------------------------------------------------------- 1. Release --
if ($Version -eq "latest") {
    $apiUrl = "https://api.github.com/repos/$Repo/releases/latest"
} else {
    $apiUrl = "https://api.github.com/repos/$Repo/releases/tags/v$($Version.TrimStart('v'))"
}

Write-Step "Consultando la version..."
try {
    $release = Invoke-RestMethod -Uri $apiUrl -Headers @{ "User-Agent" = "install-script" }
} catch {
    throw "No se pudo consultar la release en GitHub: $($_.Exception.Message)"
}

$tag = $release.tag_name
$asset = $release.assets | Where-Object { $_.name -like "*-win-*.zip" } | Select-Object -First 1
if (-not $asset) {
    throw "La release $tag no incluye un paquete para Windows."
}
$checksums = $release.assets | Where-Object { $_.name -eq "SHA256SUMS.txt" } | Select-Object -First 1
Write-Step "Version $tag"

if ((Get-Process -Name $AppName -ErrorAction SilentlyContinue)) {
    throw "La aplicacion esta abierta. Cierrala y vuelve a intentarlo."
}

# --------------------------------------------------------------- 2. Descarga --
$workDir = Join-Path $env:TEMP "$AppName-$tag"
New-Item -ItemType Directory -Force -Path $workDir | Out-Null
$zipPath = Join-Path $workDir $asset.name

Write-Step "Descargando $($asset.name) ($([math]::Round($asset.size / 1MB, 1)) MB)..."
$progress = if ($Quiet) { "SilentlyContinue" } else { "Continue" }
$previousProgress = $ProgressPreference
$ProgressPreference = $progress
try {
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -UseBasicParsing
} finally {
    $ProgressPreference = $previousProgress
}

# ------------------------------------------------------------- 3. Verificacion --
# PowerShell 7 devuelve Content como Byte[] en algunos casos, asi que se
# normaliza a texto antes de buscar la linea del checksum.
$expected = $null
if ($checksums) {
    Write-Step "Verificando el checksum..."
    $raw = (Invoke-WebRequest -Uri $checksums.browser_download_url -UseBasicParsing).Content
    if ($raw -is [byte[]]) {
        $raw = [System.Text.Encoding]::UTF8.GetString($raw)
    }
    $line = ([string]$raw -split "`r?`n") |
        Where-Object { $_ -match [regex]::Escape($asset.name) } |
        Select-Object -First 1
    if ($line) {
        $expected = (($line -split '\s+') | Select-Object -First 1).ToLower()
    }
}

if ($expected) {
    $actual = (Get-FileHash -Path $zipPath -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $expected) {
        Remove-Item -Path $zipPath -Force -ErrorAction SilentlyContinue
        throw "El checksum NO coincide: la descarga se ha descartado.`n  esperado: $expected`n  obtenido: $actual"
    }
    Write-Step "Checksum correcto."
} elseif ($AllowUnverified) {
    Write-Warning "No hay checksum publicado para este archivo; se continua por -AllowUnverified."
} else {
    Remove-Item -Path $zipPath -Force -ErrorAction SilentlyContinue
    throw ("No se pudo verificar la descarga: la release no publica SHA256SUMS.txt o no " +
        "incluye este archivo. Si asumes el riesgo, repite con -AllowUnverified.")
}

# --------------------------------------------------------------- 4. Instalacion --
if (Test-Path $InstallDir) {
    Write-Step "Actualizando la instalacion anterior..."
    Remove-Item -Path $InstallDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Write-Step "Instalando en $InstallDir"
Expand-Archive -Path $zipPath -DestinationPath $InstallDir -Force

$exePath = Join-Path $InstallDir "$AppName.exe"
if (-not (Test-Path $exePath)) {
    throw "Tras descomprimir no se encontro $AppName.exe"
}
Remove-Item -Path $workDir -Recurse -Force -ErrorAction SilentlyContinue

# --------------------------------------------------------------- 5. Accesos --
if (-not $NoShortcut) {
    Write-Step "Creando accesos directos..."
    $shell = New-Object -ComObject WScript.Shell

    $startMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "$AppName.lnk"
    $desktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk"

    foreach ($linkPath in @($startMenu, $desktop)) {
        try {
            $shortcut = $shell.CreateShortcut($linkPath)
            $shortcut.TargetPath = $exePath
            $shortcut.WorkingDirectory = $InstallDir
            $shortcut.IconLocation = "$exePath,0"
            $shortcut.Description = "Generador de clave de TikTok Live (via Streamlabs)"
            $shortcut.Save()
        } catch {
            Write-Warning "No se pudo crear el acceso directo $linkPath"
        }
    }
}

Write-Host ""
Write-Host "  Instalado correctamente." -ForegroundColor Green
Write-Host "  Programa : $exePath"
if (-not $NoShortcut) {
    Write-Host "  Accesos  : escritorio y menu Inicio"
}
Write-Host "  Desinstalar: borra la carpeta de arriba y los accesos directos." -ForegroundColor DarkGray
Write-Host ""
