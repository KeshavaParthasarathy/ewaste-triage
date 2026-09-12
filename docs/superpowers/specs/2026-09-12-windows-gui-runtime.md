# Windows GUI Runtime Recovery Spec

## Problem

The released Windows ZIP starts successfully in CI test mode but crashes for a user after normal browser download and extraction. The crash occurs when pywebview imports pythonnet and the .NET Framework loader cannot resolve `Python.Runtime.Loader.Initialize` from the bundled `Python.Runtime.dll`.

## Requirements

- A normally downloaded and extracted Windows 11 x64 package must load the bundled pywebview GUI runtime without asking the user to unblock files manually.
- The package must include a process-level .NET Framework configuration that allows its bundled, Internet-zone-marked managed assemblies to load.
- CI must exercise the real bundled CLR import after applying an Internet-zone mark; server-only test mode is insufficient.
- The bundle verifier must reject packages that omit or weaken the required CLR configuration.
- Mac packaging, application behavior, and the approved monochrome UI remain unchanged.

