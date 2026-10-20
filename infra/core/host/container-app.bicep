param name string
param location string = resourceGroup().location
param tags object = {}
param environmentId string
param storageName string
param containerImageName string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      ingress: {
        external: true
        targetPort: 8081
        transport: 'auto'
      }
    }
    template: {
      volumes: [
        {
          name: 'state-volume'
          storageType: 'AzureFile'
          storageName: storageName
        }
      ]
      containers: [
        {
          name: 'jlengine'
          image: containerImageName
          env: [
            {
              name: 'SPARKBYTE_HOST'
              value: '0.0.0.0'
            }
            {
              name: 'SPARKBYTE_PORT'
              value: '8081'
            }
            {
              name: 'SPARKBYTE_LAUNCH_BROWSER'
              value: '0'
            }
            {
              name: 'SPARKBYTE_SKIP_PKG_INSTANTIATE'
              value: '1'
            }
            {
              name: 'SPARKBYTE_STATE_DIR'
              value: '/app/runtime'
            }
            {
              name: 'A2A_HOST'
              value: '0.0.0.0'
            }
            {
              name: 'A2A_PORT'
              value: '8082'
            }
            {
              name: 'JULIAN_MANAGED_SERVICE'
              value: '1'
            }
            {
              name: 'JULIAN_AUTONOMOUS_SECONDS'
              value: '-1'
            }
          ]
          resources: {
            cpu: json('1.0')
            memory: '2.0Gi'
          }
          volumeMounts: [
            {
              volumeName: 'state-volume'
              mountPath: '/app/runtime'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

output systemAssignedMIPrincipalId string = app.identity.principalId
output name string = app.name
output uri string = 'https://${app.properties.configuration.ingress.fqdn}'
output imageName string = app.properties.template.containers[0].image
