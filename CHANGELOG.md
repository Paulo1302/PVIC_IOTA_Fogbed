# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### 🔒 Security - 2026-03-30

**CRITICAL FIX: Removed automatic container deletion that could affect other projects**

#### Changed
- **examples/04_auto_transfer_network.py**: Removed automatic container deletion in `cleanup_previous_runs()` function
  - Now displays warning message requesting manual cleanup
  - Prevents accidental deletion of containers from other Mininet/Fogbed projects
  
- **examples/02_complete_network.py**: Removed automatic container deletion in `main()` function
  - Added security warning message
  - Instructs users to verify containers before manual removal

- **README.md**: Enhanced security documentation
  - Added security warning in Quick Start section
  - Updated Troubleshooting section with safe cleanup options
  - Added reference to new `safe_cleanup.sh` script

- **AUTOMATIC_TRANSFERS_GUIDE.md**: Added security warnings
  - Updated Quick Start with container verification steps
  - Enhanced Troubleshooting Matrix with safe removal options

- **examples/04_auto_transfer_network.md**: Updated cleanup instructions
  - Added step-by-step safe cleanup process
  - Warning messages before bulk removal commands

#### Added
- **scripts/safe_cleanup.sh**: New safe cleanup utility
  - Lists all Mininet/Fogbed containers before removal
  - Requests user confirmation
  - Prevents accidental deletion of containers from other projects
  - Provides clear warnings and instructions

#### Why This Change Was Critical
The previous implementation used:
```bash
docker rm -f $(docker ps -aq --filter "name=mn.")
```

This command removes **ALL** containers with the `mn.` prefix (Mininet/Fogbed naming convention), which could include:
- Containers from other Fogbed projects
- Containers from other Mininet experiments
- Any container following the `mn.*` naming pattern

**Impact**: Users running multiple Fogbed/Mininet projects could have containers from unrelated projects accidentally deleted, causing data loss and disruption.

**Solution**: 
1. Removed all automatic deletion commands
2. Added clear warning messages
3. Created `safe_cleanup.sh` script with confirmation prompts
4. Updated all documentation with safe cleanup procedures

#### Migration Guide
If you were using the examples directly:

**Before (UNSAFE)**:
```bash
# This ran automatically in examples
docker rm -f $(docker ps -aq --filter "name=mn.")
```

**After (SAFE)**:
```bash
# Option 1: Use the safe script
./scripts/safe_cleanup.sh

# Option 2: Manual cleanup
docker ps -a --filter "name=mn."  # List first
docker rm -f <specific_container_id>  # Remove specific ones
sudo mn -c
```

---

## [0.1.0] - Initial Release

### Added
- Initial release of fogbed-iota
- IOTA blockchain integration with Fogbed/Mininet
- Automatic genesis generation
- Smart contract support
- Account management
- Automatic transfers without faucet
- RPC client and CLI integration
- Complete documentation and examples
