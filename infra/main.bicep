targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the the environment which is used to generate a short unique hash used in all resources.')
param name string

@minLength(1)
@description('Primary location for all resources')
param location string

var resourceToken = toLower(uniqueString(subscription().id, name, location))
var tags = { 'azd-env-name': name }

// Organize resources in a resource group
resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: 'rg-${name}'
  location: location
  tags: tags
}

// 1. Log Analytics Workspace
module logAnalytics './core/host/log-analytics.bicep' = {
  name: 'log-analytics'
  scope: rg
  params: {
    name: 'log-${name}-${resourceToken}'
    location: location
    tags: tags
  }
}

// 2. Storage Account & File Share for persistent SQLite state
module storage './core/storage/storage-account.bicep' = {
  name: 'storage'
  scope: rg
  params: {
    name: 'stor${resourceToken}'
    location: location
    tags: tags
  }
}

// 3. Container Apps Environment (with Storage Link)
module containerAppsEnvironment './core/host/container-apps-environment.bicep' = {
  name: 'container-apps-environment'
  scope: rg
  params: {
    name: 'cae-${name}-${resourceToken}'
    location: location
    tags: tags
    logAnalyticsWorkspaceId: logAnalytics.outputs.id
    storageAccountName: storage.outputs.name
    storageAccountKey: storage.outputs.key
    fileShareName: storage.outputs.fileShareName
  }
}

// 4. Container Registry
module containerRegistry './core/host/container-registry.bicep' = {
  name: 'container-registry'
  scope: rg
  params: {
    // Alphanumeric only, 5-50 characters
    name: replace('cr${name}${resourceToken}', '-', '')
    location: location
    tags: tags
  }
}

// 5. Container App (Phase 1: No Registry Link)
module app './core/host/container-app.bicep' = {
  name: 'container-app'
  scope: rg
  params: {
    name: 'ca-${name}'
    location: location
    tags: tags
    environmentId: containerAppsEnvironment.outputs.id
    storageName: containerAppsEnvironment.outputs.storageName
    // We use a public placeholder image initially so AZD can link the identity 
    // before pushing the actual private image.
    containerImageName: 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
  }
}

// 6. ACR Pull Role Assignment (Phase 2: Prevents circular dependency)
module acrPullRole './core/host/acr-pull-role.bicep' = {
  name: 'acr-pull-role'
  scope: rg
  params: {
    acrName: containerRegistry.outputs.name
    principalId: app.outputs.systemAssignedMIPrincipalId
  }
}

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = containerRegistry.outputs.loginServer
output AZURE_CONTAINER_ENVIRONMENT_NAME string = containerAppsEnvironment.outputs.name
output SERVICE_API_IDENTITY_PRINCIPAL_ID string = app.outputs.systemAssignedMIPrincipalId
output SERVICE_API_NAME string = app.outputs.name
output SERVICE_API_URI string = app.outputs.uri
output SERVICE_API_IMAGE_NAME string = app.outputs.imageName
