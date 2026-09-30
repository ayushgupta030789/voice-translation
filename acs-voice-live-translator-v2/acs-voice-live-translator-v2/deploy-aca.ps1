param(
  [Parameter(Mandatory=$true)][string]$ResourceGroup,
  [Parameter(Mandatory=$true)][string]$ContainerAppName,
  [Parameter(Mandatory=$true)][string]$EnvironmentName,
  [Parameter(Mandatory=$true)][string]$AcrName,
  [string]$ImageName = "acs-voice-live-translator-v2",
  [string]$ImageTag = "v2"
)

$ErrorActionPreference = "Stop"
$registry = az acr show --name $AcrName --query loginServer -o tsv
if (-not $registry) { throw "Could not resolve ACR login server for $AcrName" }
$image = "$registry/${ImageName}:$ImageTag"

Write-Host "Building image $image using ACR build..."
az acr build --registry $AcrName --image "${ImageName}:$ImageTag" --file Dockerfile .
if ($LASTEXITCODE -ne 0) { throw "az acr build failed. If ACR Tasks are disabled, build with an approved external builder and push the image." }

Write-Host "Creating/updating Container App. This script creates a basic app only if it does not already exist."
$exists = az containerapp show --name $ContainerAppName --resource-group $ResourceGroup --query name -o tsv 2>$null
if (-not $exists) {
  az containerapp create --name $ContainerAppName --resource-group $ResourceGroup --environment $EnvironmentName --image $image --target-port 8080 --ingress external --min-replicas 1 --max-replicas 1
} else {
  az containerapp update --name $ContainerAppName --resource-group $ResourceGroup --image $image --min-replicas 1 --max-replicas 1
}
if ($LASTEXITCODE -ne 0) { throw "Container App create/update failed" }

Write-Host "Image deployed. Configure secrets/environment variables in ACA before testing calls."
Write-Host "Required settings are listed in .env.example; do not put real secrets in source control."
