$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force ".design-reference" | Out-Null
if (-not (Test-Path ".design-reference\awesome-design-md")) {
  git clone https://github.com/VoltAgent/awesome-design-md.git .design-reference/awesome-design-md
}
Write-Host "Design reference cloned. Root DESIGN.md remains the product source of truth."
