# 0006: Keep ledger records in Git and slices in releases

Append compact forecast and audit records to the separate `ledger` branch, and store compressed ensemble slices and their metadata in monthly releases of a separate archive repository. The records support an auditable history while the slices retain the member data and launch context needed to rescore forecasts after rule changes. Keeping data releases outside the software repository also prevents archive releases from creating software DOI versions; archive access and retention become operational requirements.
