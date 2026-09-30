# Example deployment script.
# Adjust resource names to your environment.

$RESOURCE_GROUP = "rg-voice-live-demo"
$ACA_ENVIRONMENT = "aca-env-voice-live"
$ACA_APP = "acs-voice-live-translator"
$LOCATION = "eastus2"

az containerapp up `
  --name $ACA_APP `
  --resource-group $RESOURCE_GROUP `
  --environment $ACA_ENVIRONMENT `
  --location $LOCATION `
  --source . `
  --target-port 8080 `
  --ingress external `
  --min-replicas 1 `
  --max-replicas 1

Write-Host "Deployment submitted."
Write-Host "Configure the environment variables/secrets in ACA before testing calls."
