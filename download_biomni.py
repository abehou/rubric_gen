from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="phylobio/BiomniBench-DA",
    repo_type="dataset",
    local_dir="/juice2/u/nlp/abe_models/biomnibench-da",
    ignore_patterns=["da-1-3/**", "da-1-4/**", "da-17-1/**", "da-17-3/**", "da-17-5/**"]
)

