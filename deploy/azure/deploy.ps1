<#
.SYNOPSIS
    Deploy the AI Tuition Assistant to Azure.

.DESCRIPTION
    Creates (or updates) in one resource group:
      - Azure Database for PostgreSQL Flexible Server (Burstable B1ms) + database "tuition"
      - Azure Container Registry (Basic); images are built in the cloud with "az acr build"
      - Azure Container Apps environment with three apps:
          <prefix>-api      Tuition REST API   (internal ingress: reachable only from the gateway)
          <prefix>-mcp      MCP policy server  (external HTTPS ingress, path /mcp)
          <prefix>-gateway  Kong API Gateway   (external HTTPS ingress: the public REST entry point)

    Secrets are read from the repository's .env file and stored as Container Apps secrets:
      JWT_SECRET               32+ characters, letters/digits/-/_ only, not the .env.example value
      SEED_DEMO_PASSWORD       password of the demo users
      AZURE_POSTGRES_PASSWORD  12+ characters, letters and digits only, with upper case, lower case and a digit

    Prerequisites: Azure CLI logged in (az login), subscription selected. Docker is not needed.

.EXAMPLE
    ./deploy/azure/deploy.ps1 -DryRun                  # print the plan, call nothing
    ./deploy/azure/deploy.ps1 -Location westeurope     # deploy
#>
param(
    [string]$Location = "westeurope",
    [string]$ResourceGroup = "rg-tuition-assistant",
    [string]$Prefix = "tuition",
    [string]$EnvFile = "",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $EnvFile) { $EnvFile = Join-Path $RepoRoot ".env" }

# --- helpers ---------------------------------------------------------------------------------------

function Read-DotEnv([string]$Path) {
    if (-not (Test-Path $Path)) { throw ".env not found at $Path (copy .env.example to .env)" }
    $values = @{}
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { $values[$Matches[1]] = $Matches[2].Trim() }
    }
    return $values
}

function Get-RequiredSetting([string]$Name, [string]$Pattern, [string]$Rule) {
    $value = $Settings[$Name]
    if (-not $value) { throw "$Name must be set in .env" }
    if ($value -notmatch $Pattern) { throw "$Name is not valid: $Rule" }
    return $value
}

function Write-Step([string]$Text) { Write-Host "`n==> $Text" -ForegroundColor Cyan }

# Runs az; never prints the arguments (they may contain secrets).
# -Stream shows the command's output live (for long steps) instead of returning it.
function Invoke-Az([string]$Label, [string[]]$Arguments, [string]$DryRunResult = "dry-run-value", [switch]$Stream) {
    if ($DryRun) {
        Write-Host "    [dry-run] az $($Arguments[0]) $($Arguments[1]) ... ($Label)"
        return $DryRunResult
    }
    if ($Stream) {
        & az @Arguments --only-show-errors | Out-Host
        $output = $null
    } else {
        $output = & az @Arguments --only-show-errors
    }
    if ($LASTEXITCODE -ne 0) { throw "Azure CLI step failed: $Label" }
    return $output
}

# True if the az command succeeds (used for "does it already exist" checks).
function Test-Az([string[]]$Arguments) {
    if ($DryRun) { return $false }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & az @Arguments --only-show-errors *> $null
    $ok = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $previous
    return $ok
}

# --- settings --------------------------------------------------------------------------------------

$Settings = Read-DotEnv $EnvFile
$JwtSecret = Get-RequiredSetting "JWT_SECRET" '^[A-Za-z0-9_-]{32,}$' "at least 32 characters: letters, digits, - or _"
if ($JwtSecret -eq "change-me-to-a-long-random-string") { throw "JWT_SECRET still has the public .env.example value" }
$SeedPassword = Get-RequiredSetting "SEED_DEMO_PASSWORD" '^[A-Za-z0-9_.-]{8,}$' "at least 8 characters: letters, digits, _ . -"
$PgPassword = Get-RequiredSetting "AZURE_POSTGRES_PASSWORD" '^(?=.*[a-z])(?=.*[A-Z])(?=.*[0-9])[A-Za-z0-9]{12,}$' `
    "12+ letters and digits with an upper case letter, a lower case letter and a digit"

$PgAdmin = "tuitionadmin"
$PgDatabase = "tuition"
$EnvName = "$Prefix-env"
$ApiApp = "$Prefix-api"
$McpApp = "$Prefix-mcp"
$GatewayApp = "$Prefix-gateway"

Write-Step "Checking Azure login"
$SubscriptionId = Invoke-Az "account show" @("account", "show", "--query", "id", "-o", "tsv") "00000000-dry-run"
$SubscriptionName = Invoke-Az "account show" @("account", "show", "--query", "name", "-o", "tsv") "Azure for Students"
Write-Host "    Subscription: $SubscriptionName"

# Globally unique names derived from the subscription ID (stable across re-runs).
$Suffix = ($SubscriptionId -replace '[^a-z0-9]', '').Substring(0, 6)
$AcrName = "${Prefix}acr$Suffix"
$PgServer = "$Prefix-pg-$Suffix"
Write-Host "    Resource group: $ResourceGroup ($Location), registry: $AcrName, PostgreSQL: $PgServer"

# --- infrastructure --------------------------------------------------------------------------------

Write-Step "Registering resource providers (first time only, may take a few minutes)"
foreach ($ns in "Microsoft.App", "Microsoft.OperationalInsights", "Microsoft.DBforPostgreSQL", "Microsoft.ContainerRegistry") {
    Invoke-Az "provider register $ns" @("provider", "register", "--namespace", $ns, "--wait") | Out-Null
}
Invoke-Az "containerapp extension" @("extension", "add", "--name", "containerapp", "--upgrade") | Out-Null

Write-Step "Resource group"
Invoke-Az "group create" @("group", "create", "--name", $ResourceGroup, "--location", $Location, "-o", "none") | Out-Null

Write-Step "Container Registry"
if (-not (Test-Az @("acr", "show", "--name", $AcrName))) {
    Invoke-Az "acr create" @("acr", "create", "--name", $AcrName, "--resource-group", $ResourceGroup,
        "--location", $Location, "--sku", "Basic", "--admin-enabled", "true", "-o", "none") | Out-Null
}
$AcrServer = Invoke-Az "acr show" @("acr", "show", "--name", $AcrName, "--query", "loginServer", "-o", "tsv") "$AcrName.azurecr.io"
$AcrPassword = Invoke-Az "acr credential" @("acr", "credential", "show", "--name", $AcrName,
    "--query", "passwords[0].value", "-o", "tsv")

Write-Step "Building images in Azure (az acr build; no local Docker needed)"
$Images = @{ "tuition-api" = "api/Dockerfile"; "tuition-mcp" = "mcp_server/Dockerfile"; "tuition-gateway" = "gateway/Dockerfile" }
foreach ($image in $Images.Keys) {
    Invoke-Az "acr build $image" @("acr", "build", "--registry", $AcrName, "--image", "${image}:latest",
        "--file", (Join-Path $RepoRoot $Images[$image]), $RepoRoot) -Stream | Out-Null
}

Write-Step "PostgreSQL Flexible Server (first creation takes 5-10 minutes)"
if (-not (Test-Az @("postgres", "flexible-server", "show", "--resource-group", $ResourceGroup, "--name", $PgServer))) {
    # --public-access 0.0.0.0 allows connections from Azure services only (no public client IPs).
    Invoke-Az "postgres create" @("postgres", "flexible-server", "create", "--resource-group", $ResourceGroup,
        "--name", $PgServer, "--location", $Location, "--admin-user", $PgAdmin, "--admin-password", $PgPassword,
        "--tier", "Burstable", "--sku-name", "Standard_B1ms", "--storage-size", "32", "--version", "16",
        "--public-access", "0.0.0.0", "--yes", "-o", "none") -Stream | Out-Null
}
if (-not (Test-Az @("postgres", "flexible-server", "db", "show", "--resource-group", $ResourceGroup,
        "--server-name", $PgServer, "--database-name", $PgDatabase))) {
    Invoke-Az "postgres db create" @("postgres", "flexible-server", "db", "create", "--resource-group", $ResourceGroup,
        "--server-name", $PgServer, "--database-name", $PgDatabase, "-o", "none") | Out-Null
}
$PgHost = Invoke-Az "postgres show" @("postgres", "flexible-server", "show", "--resource-group", $ResourceGroup,
    "--name", $PgServer, "--query", "fullyQualifiedDomainName", "-o", "tsv") "$PgServer.postgres.database.azure.com"
$DatabaseUrl = "postgresql+psycopg://${PgAdmin}:${PgPassword}@${PgHost}:5432/${PgDatabase}?sslmode=require"

Write-Step "Container Apps environment"
if (-not (Test-Az @("containerapp", "env", "show", "--resource-group", $ResourceGroup, "--name", $EnvName))) {
    Invoke-Az "containerapp env create" @("containerapp", "env", "create", "--resource-group", $ResourceGroup,
        "--name", $EnvName, "--location", $Location, "-o", "none") | Out-Null
}

# --- apps ------------------------------------------------------------------------------------------

function Deploy-App([string]$Name, [string]$Image, [string]$Ingress, [int]$Port, [string[]]$Secrets, [string[]]$EnvVars) {
    Write-Step "Container App $Name"
    $imageRef = "$AcrServer/${Image}:latest"
    $stamp = "DEPLOYED_AT=$(Get-Date -Format 'yyyyMMddHHmmss')"  # forces a new revision for the same tag
    if (Test-Az @("containerapp", "show", "--resource-group", $ResourceGroup, "--name", $Name)) {
        if ($Secrets.Count -gt 0) {
            Invoke-Az "secret set $Name" (@("containerapp", "secret", "set", "--resource-group", $ResourceGroup,
                "--name", $Name, "--secrets") + $Secrets + @("-o", "none")) | Out-Null
        }
        Invoke-Az "containerapp update $Name" (@("containerapp", "update", "--resource-group", $ResourceGroup,
            "--name", $Name, "--image", $imageRef, "--set-env-vars") + $EnvVars + @($stamp, "-o", "none")) | Out-Null
    } else {
        $arguments = @("containerapp", "create", "--resource-group", $ResourceGroup, "--name", $Name,
            "--environment", $EnvName, "--image", $imageRef,
            "--registry-server", $AcrServer, "--registry-username", $AcrName, "--registry-password", $AcrPassword,
            "--ingress", $Ingress, "--target-port", "$Port", "--cpu", "0.25", "--memory", "0.5Gi",
            "--min-replicas", "1", "--max-replicas", "1", "-o", "none")
        if ($Secrets.Count -gt 0) { $arguments += @("--secrets") + $Secrets }
        $arguments += @("--env-vars") + $EnvVars + @($stamp)
        Invoke-Az "containerapp create $Name" $arguments | Out-Null
    }
}

Deploy-App $ApiApp "tuition-api" "internal" 8080 `
    @("jwt-secret=$JwtSecret", "database-url=$DatabaseUrl", "seed-password=$SeedPassword") `
    @("JWT_SECRET=secretref:jwt-secret", "DATABASE_URL=secretref:database-url",
      "SEED_DEMO_PASSWORD=secretref:seed-password", "SEED_ON_START=true", "APP_TIMEZONE=Europe/Istanbul")

Deploy-App $McpApp "tuition-mcp" "external" 8001 @() @("MCP_HOST=0.0.0.0", "MCP_PORT=8001")

# Inside the environment the API is reachable by its app name over internal ingress (port 80).
Deploy-App $GatewayApp "tuition-gateway" "external" 8000 @("jwt-secret=$JwtSecret") `
    @("JWT_SECRET=secretref:jwt-secret", "API_UPSTREAM=http://$ApiApp")

# --- result ----------------------------------------------------------------------------------------

Write-Step "Deployment finished"
$GatewayFqdn = Invoke-Az "gateway fqdn" @("containerapp", "show", "--resource-group", $ResourceGroup, "--name", $GatewayApp,
    "--query", "properties.configuration.ingress.fqdn", "-o", "tsv") "$GatewayApp.example.azurecontainerapps.io"
$McpFqdn = Invoke-Az "mcp fqdn" @("containerapp", "show", "--resource-group", $ResourceGroup, "--name", $McpApp,
    "--query", "properties.configuration.ingress.fqdn", "-o", "tsv") "$McpApp.example.azurecontainerapps.io"

Write-Host "    Gateway (REST):  https://$GatewayFqdn"
Write-Host "    Swagger UI:      https://$GatewayFqdn/docs"
Write-Host "    MCP server:      https://$McpFqdn/mcp"
Write-Host "`n    To point the agent at the cloud, set in .env:"
Write-Host "      GATEWAY_BASE_URL=https://$GatewayFqdn"
Write-Host "      MCP_SERVER_URL=https://$McpFqdn/mcp"
Write-Host "`n    Delete everything afterwards:  az group delete --name $ResourceGroup --yes --no-wait"

if (-not $DryRun) {
    Write-Step "Health check through the gateway (the API may need a minute to start)"
    for ($i = 1; $i -le 12; $i++) {
        try {
            $health = Invoke-RestMethod -Uri "https://$GatewayFqdn/api/v1/health" -TimeoutSec 10
            Write-Host "    OK: $($health.service) $($health.status)"
            break
        } catch {
            Write-Host "    not ready yet ($i/12), retrying in 10 s"
            Start-Sleep -Seconds 10
        }
    }
}
