Param(
  [string]$Base = $env:BASE ? $env:BASE : "http://localhost:8000",
  [string]$Token = $env:TOKEN,
  [string]$ProjectId = $env:PROJECT_ID,
  [string]$PdfFile = $env:PDF_FILE ? $env:PDF_FILE : "examples/pdfs/sample.pdf",
  [string]$ZipFile = $env:ZIP_FILE ? $env:ZIP_FILE : "examples/bundles/report_small.zip",
  [string]$ExportPreset = $env:EXPORT_PRESET ? $env:EXPORT_PRESET : "rag"
)
function Say($msg) { Write-Host "`n▸ $msg" }
$headers = @{}; if ($Token) { $headers["Authorization"]="Bearer $Token" } else { $headers["X-Role"]="curator" }
Say "Checking API health at $Base/health"
Invoke-RestMethod -Uri "$Base/health" -Headers $headers -Method GET | ConvertTo-Json
if (-not $ProjectId) {
  try { $projects = Invoke-RestMethod -Uri "$Base/projects" -Headers $headers -Method GET
        if ($projects.projects.Count -gt 0) { $ProjectId = $projects.projects[0].id } } catch {}
}
if (-not $ProjectId) { Write-Error "PROJECT_ID not set and /projects unavailable/empty."; exit 1 }
Say "Using PROJECT_ID=$ProjectId"
if (-not (Test-Path $PdfFile)) { Write-Error "PDF_FILE '$PdfFile' not found."; exit 1 }
Say "Ingesting PDF $PdfFile"
$Form = @{ project_id = $ProjectId; file = Get-Item $PdfFile }
$resp = Invoke-RestMethod -Uri "$Base/ingest" -Headers $headers -Method Post -Form $Form
$DocId = $resp.doc_id; Write-Host "DOC_ID=$DocId"
Say "Waiting for parse completion for DOC_ID=$DocId"
$max=60; for ($i=1; $i -le $max; $i++) {
  $docs = Invoke-RestMethod -Uri "$Base/documents?project_id=$ProjectId&limit=200" -Headers $headers -Method GET
  $row = $docs.documents | Where-Object { $_.id -eq $DocId }
  if ($row) { $status=$row.status; $hasParse = $row.metadata.parse -ne $null
    Write-Host ("  try={0} status={1} parse_field={2}" -f $i,$status,$hasParse); if ($hasParse) { break } }
  Start-Sleep -Seconds 2
}
if (-not $hasParse) { Write-Error "Parsing timed out."; exit 1 }
Say "Fetching document metrics"
Invoke-RestMethod -Uri "$Base/documents/$DocId/metrics" -Headers $headers -Method GET | ConvertTo-Json
Say "Exporting JSONL with preset=$ExportPreset"
$payload = @{ project_id=$ProjectId; doc_ids=@($DocId); preset=$ExportPreset } | ConvertTo-Json
$exp = Invoke-RestMethod -Uri "$Base/export/jsonl" -Headers ($headers + @{"Content-Type"="application/json"}) -Method Post -Body $payload
$exp | ConvertTo-Json; $url=$exp.url; if (-not $url) { Write-Error "No export URL."; exit 1 }
Say "Downloading export to $env:TEMP\export.jsonl"
Invoke-WebRequest -Uri $url -OutFile "$env:TEMP\export.jsonl"; Get-Content "$env:TEMP\export.jsonl" -TotalCount 3
if (Test-Path $ZipFile) {
  Say "Ingesting HTML ZIP bundle $ZipFile"
  $Form2 = @{ project_id=$ProjectId; file=Get-Item $ZipFile }
  $resp2 = Invoke-RestMethod -Uri "$Base/ingest/zip" -Headers $headers -Method Post -Form $Form2
  $Doc2Id=$resp2.doc_id; Write-Host "DOC2_ID=$Doc2Id"
} else { Write-Host "Skipping ZIP ingest; file '$ZipFile' not found." }
Say "E2E smoke complete ✅"
