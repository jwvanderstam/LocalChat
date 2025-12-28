# LocalChat Installation Script for Windows
# ==========================================
# Automated installation script for LocalChat RAG application on Windows
# 
# Usage:
#   .\install.ps1                    # Interactive installation
#   .\install.ps1 -Auto              # Automatic installation
#   .\install.ps1 -CheckOnly         # Check prerequisites only
#
# Author: LocalChat Team
# Date: 2024-12-28

param(
    [switch]$Auto,
    [switch]$CheckOnly
)

# Colors for output
$Colors = @{
    Success = "Green"
    Error = "Red"
    Warning = "Yellow"
    Info = "Cyan"
    Header = "Magenta"
}

function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor $Colors.Header
    Write-Host $Text -ForegroundColor $Colors.Header
    Write-Host ("=" * 70) -ForegroundColor $Colors.Header
    Write-Host ""
}

function Write-Success {
    param([string]$Text)
    Write-Host "? $Text" -ForegroundColor $Colors.Success
}

function Write-ErrorMsg {
    param([string]$Text)
    Write-Host "? $Text" -ForegroundColor $Colors.Error
}

function Write-WarningMsg {
    param([string]$Text)
    Write-Host "? $Text" -ForegroundColor $Colors.Warning
}

function Write-InfoMsg {
    param([string]$Text)
    Write-Host "? $Text" -ForegroundColor $Colors.Info
}

function Test-PythonVersion {
    Write-InfoMsg "Checking Python version..."
    
    try {
        $pythonVersion = python --version 2>&1
        if ($pythonVersion -match "Python (\d+)\.(\d+)\.(\d+)") {
            $major = [int]$matches[1]
            $minor = [int]$matches[2]
            $patch = [int]$matches[3]
            
            if ($major -ge 3 -and $minor -ge 10) {
                Write-Success "Python $major.$minor.$patch detected"
                return $true
            } else {
                Write-ErrorMsg "Python 3.10+ required, found $major.$minor.$patch"
                return $false
            }
        }
    } catch {
        Write-ErrorMsg "Python not found"
        Write-InfoMsg "Install from: https://www.python.org/downloads/"
        return $false
    }
    
    return $false
}

function Test-PostgreSQL {
    Write-InfoMsg "Checking PostgreSQL..."
    
    try {
        $psqlVersion = psql --version 2>&1
        if ($psqlVersion -match "psql") {
            Write-Success "PostgreSQL is installed"
            
            # Check if server is running
            try {
                $result = pg_isready 2>&1
                if ($LASTEXITCODE -eq 0) {
                    Write-Success "PostgreSQL server is running"
                    return $true
                } else {
                    Write-WarningMsg "PostgreSQL is installed but server is not running"
                    Write-InfoMsg "Start PostgreSQL server and run install again"
                    return $false
                }
            } catch {
                Write-WarningMsg "Cannot check PostgreSQL server status"
                return $false
            }
        }
    } catch {
        Write-ErrorMsg "PostgreSQL is not installed"
        Write-InfoMsg "Install from: https://www.postgresql.org/download/windows/"
        return $false
    }
    
    return $false
}

function Test-Ollama {
    Write-InfoMsg "Checking Ollama..."
    
    try {
        $ollamaVersion = ollama --version 2>&1
        if ($ollamaVersion -match "ollama") {
            Write-Success "Ollama is installed"
            
            # Check if server is running
            try {
                $response = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
                if ($response.StatusCode -eq 200) {
                    Write-Success "Ollama server is running"
                    return $true
                }
            } catch {
                Write-WarningMsg "Ollama is installed but server is not running"
                Write-InfoMsg "Run 'ollama serve' in another terminal"
                return $false
            }
        }
    } catch {
        Write-ErrorMsg "Ollama is not installed"
        Write-InfoMsg "Install from: https://ollama.ai"
        return $false
    }
    
    return $false
}

function Install-PythonDependencies {
    Write-InfoMsg "Installing Python dependencies..."
    
    if (-not (Test-Path "requirements.txt")) {
        Write-ErrorMsg "requirements.txt not found"
        return $false
    }
    
    try {
        python -m pip install -r requirements.txt
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Python dependencies installed"
            return $true
        } else {
            Write-ErrorMsg "Failed to install Python dependencies"
            return $false
        }
    } catch {
        Write-ErrorMsg "Failed to install Python dependencies: $_"
        return $false
    }
}

function Setup-Database {
    Write-InfoMsg "Setting up database..."
    
    $dbName = Read-Host "Enter database name (default: rag_db)"
    if ([string]::IsNullOrWhiteSpace($dbName)) {
        $dbName = "rag_db"
    }
    
    # Check if database exists
    try {
        $databases = psql -lqt 2>&1
        if ($databases -match $dbName) {
            Write-WarningMsg "Database '$dbName' already exists"
            $response = Read-Host "Do you want to use existing database? (y/n)"
            if ($response -ne 'y') {
                return $false
            }
        } else {
            # Create database
            Write-InfoMsg "Creating database '$dbName'..."
            createdb $dbName
            if ($LASTEXITCODE -eq 0) {
                Write-Success "Database '$dbName' created"
            } else {
                Write-ErrorMsg "Failed to create database '$dbName'"
                return $false
            }
        }
    } catch {
        Write-ErrorMsg "Error checking database: $_"
        return $false
    }
    
    # Enable pgvector extension
    Write-InfoMsg "Enabling pgvector extension..."
    try {
        psql $dbName -c "CREATE EXTENSION IF NOT EXISTS vector;"
        if ($LASTEXITCODE -eq 0) {
            Write-Success "pgvector extension enabled"
        } else {
            Write-ErrorMsg "Failed to enable pgvector extension"
            Write-InfoMsg "You may need to install pgvector first:"
            Write-InfoMsg "https://github.com/pgvector/pgvector"
            return $false
        }
    } catch {
        Write-ErrorMsg "Error enabling pgvector: $_"
        return $false
    }
    
    # Create .env file
    New-EnvFile -DbName $dbName
    
    return $true
}

function New-EnvFile {
    param([string]$DbName)
    
    Write-InfoMsg "Creating .env configuration file..."
    
    $envContent = @"
# LocalChat Environment Configuration
# Generated by install.ps1

# Database Configuration
PG_HOST=localhost
PG_PORT=5432
PG_USER=postgres
PG_PASSWORD=postgres
PG_DB=$DbName

# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434

# Flask Configuration
SERVER_HOST=localhost
SERVER_PORT=5000
SECRET_KEY=change-this-in-production

# Application Settings
DEBUG=False
"@
    
    Set-Content -Path ".env" -Value $envContent
    Write-Success ".env file created"
    Write-WarningMsg "? Edit .env file to set your PostgreSQL password"
}

function Get-OllamaModels {
    Write-InfoMsg "Pulling Ollama models..."
    
    $models = @(
        @{Name = "nomic-embed-text"; Description = "Embedding model"},
        @{Name = "llama3.2"; Description = "Chat model"}
    )
    
    foreach ($model in $models) {
        Write-InfoMsg "Pulling $($model.Name) ($($model.Description))..."
        ollama pull $model.Name
        if ($LASTEXITCODE -eq 0) {
            Write-Success "$($model.Name) pulled successfully"
        } else {
            Write-WarningMsg "Failed to pull $($model.Name)"
            Write-InfoMsg "You can pull it later with: ollama pull $($model.Name)"
        }
    }
    
    return $true
}

function New-Directories {
    Write-InfoMsg "Creating directories..."
    
    $directories = @("logs", "uploads")
    
    foreach ($directory in $directories) {
        if (-not (Test-Path $directory)) {
            New-Item -ItemType Directory -Path $directory -Force | Out-Null
            Write-Success "Created $directory/ directory"
        } else {
            Write-InfoMsg "$directory/ directory already exists"
        }
    }
}

function Invoke-Tests {
    Write-InfoMsg "Running tests to verify installation..."
    
    try {
        python -m pytest tests/ -v --tb=short
        if ($LASTEXITCODE -eq 0) {
            Write-Success "All tests passed"
            return $true
        } else {
            Write-WarningMsg "Some tests failed (this may be normal)"
            return $true
        }
    } catch {
        Write-WarningMsg "Could not run tests: $_"
        return $true
    }
}

function Test-Prerequisites {
    Write-Header "Checking Prerequisites"
    
    $checks = @{
        "Python 3.10+" = Test-PythonVersion
        "PostgreSQL" = Test-PostgreSQL
        "Ollama" = Test-Ollama
    }
    
    $allPassed = $true
    foreach ($check in $checks.GetEnumerator()) {
        if (-not $check.Value) {
            $allPassed = $false
        }
    }
    
    Write-Host ""
    Write-Host ("=" * 70)
    if ($allPassed) {
        Write-Success "All prerequisites met!"
    } else {
        Write-ErrorMsg "Some prerequisites are missing"
        Write-InfoMsg "Install missing components and run again"
    }
    Write-Host ("=" * 70)
    
    return $allPassed
}

function Main {
    Write-Header "LocalChat Installation"
    Write-Host "Welcome to LocalChat RAG Application installer"
    Write-Host "This script will install and configure LocalChat"
    Write-Host ""
    
    # Check prerequisites
    if (-not (Test-Prerequisites)) {
        Write-ErrorMsg "`nInstallation cannot continue due to missing prerequisites"
        exit 1
    }
    
    if ($CheckOnly) {
        exit 0
    }
    
    # Confirm installation
    if (-not $Auto) {
        $response = Read-Host "`nProceed with installation? (y/n)"
        if ($response -ne 'y') {
            Write-Host "Installation cancelled"
            exit 0
        }
    }
    
    # Install Python dependencies
    Write-Header "Installing Python Dependencies"
    if (-not (Install-PythonDependencies)) {
        Write-ErrorMsg "Installation failed"
        exit 1
    }
    
    # Set up database
    Write-Header "Setting Up Database"
    if (-not $Auto) {
        if (-not (Setup-Database)) {
            Write-ErrorMsg "Database setup failed"
            exit 1
        }
    } else {
        Write-InfoMsg "Skipping database setup in auto mode"
        Write-InfoMsg "Run '.\install.ps1' interactively to set up database"
    }
    
    # Create directories
    Write-Header "Creating Directories"
    New-Directories
    
    # Pull Ollama models
    Write-Header "Pulling Ollama Models"
    if (-not $Auto) {
        $response = Read-Host "Do you want to pull Ollama models now? (y/n)"
        if ($response -eq 'y') {
            Get-OllamaModels
        }
    } else {
        Write-InfoMsg "Skipping Ollama models in auto mode"
        Write-InfoMsg "Run 'ollama pull nomic-embed-text' and 'ollama pull llama3.2' manually"
    }
    
    # Run tests
    if (-not $Auto) {
        Write-Header "Running Tests"
        $response = Read-Host "Do you want to run tests to verify installation? (y/n)"
        if ($response -eq 'y') {
            Invoke-Tests
        }
    }
    
    # Installation complete
    Write-Header "Installation Complete!"
    Write-Success "LocalChat has been successfully installed!"
    
    Write-Host ""
    Write-Host ("=" * 70)
    Write-Host "Next steps:"
    Write-Host "  1. Edit .env file to configure your database password"
    Write-Host "  2. Start Ollama: ollama serve"
    Write-Host "  3. Start LocalChat: python app.py"
    Write-Host "  4. Open browser: http://localhost:5000"
    Write-Host ("=" * 70)
    
    Write-Host "`nFor more information, see:"
    Write-Host "  - QUICK_START.md"
    Write-Host "  - docs\SETUP_GUIDE.md"
    Write-Host "  - README_MAIN.md"
}

# Run main function
try {
    Main
} catch {
    Write-ErrorMsg "`nInstallation failed: $_"
    exit 1
}
