param(
    [Parameter(Mandatory = $true)][string]$ProjectId,
    [Parameter(Mandatory = $true)][string]$IpAddress
)

$ErrorActionPreference = "Stop"
$certificateName = "training-server-ip"
$localDirectory = Join-Path $PSScriptRoot ".local"
$certificatePath = Join-Path $localDirectory "server.crt"
$privateKeyPath = Join-Path $localDirectory "server.key"

# Keep the private key outside Terraform state and outside version control.
New-Item -ItemType Directory -Path $localDirectory -Force | Out-Null
if ((Test-Path $certificatePath) -or (Test-Path $privateKeyPath)) {
    throw "A local server certificate already exists. Inspect .local before generating a replacement."
}

# The IP SAN lets Python and curl verify HTTPS when there is no DNS name.
& openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 30 `
    -keyout $privateKeyPath -out $certificatePath `
    -subj "/CN=$IpAddress" `
    -addext "subjectAltName=IP:$IpAddress" `
    -addext "keyUsage=digitalSignature,keyEncipherment" `
    -addext "extendedKeyUsage=serverAuth"
if ($LASTEXITCODE -ne 0) { throw "OpenSSL certificate generation failed." }

# Upload the server key directly to the load balancer certificate resource.
& gcloud compute ssl-certificates create $certificateName `
    --certificate=$certificatePath --private-key=$privateKeyPath `
    --global --project=$ProjectId
if ($LASTEXITCODE -ne 0) { throw "Certificate upload failed. Local files remain in .local." }

Write-Output "Certificate resource: $certificateName"
Write-Output "Worker trust file: $certificatePath"
Write-Output "Keep $privateKeyPath private; it is not needed on workers."
