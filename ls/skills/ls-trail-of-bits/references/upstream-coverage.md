# Upstream Coverage

- Source: `https://github.com/trailofbits/skills`
- Ref: `main` at `cfe5d7b1619e47fb5b38b7e2561dad7e5f1e89af`
- License classification: `CC-BY-SA-4.0`; governing [upstream LICENSE](https://github.com/trailofbits/skills/blob/cfe5d7b1619e47fb5b38b7e2561dad7e5f1e89af/LICENSE)
- Inventoried `SKILL.md` files: `75`
- Inventory hash: `6867b487caf10c73043a264b4bcc035f7fd943085b50545c7c0b0c996ad7fe57`

This wrapper intentionally does not expose every upstream subskill as a LocalSetup skill.
Select one upstream path at a time for future import, then run importer, vetter, normalizer, and sandbox validation.

## Inventory Manifest And Hash Recipe

The enumeration root is `.` in the pinned upstream repository. The manifest below
lists every regular `SKILL.md` file recursively beneath that root, using
repository-relative paths and SHA-256 hashes of the raw file bytes.

To reproduce the inventory hash, preserve the manifest row order below. For each
row, concatenate its path, one ASCII space, and its lowercase hexadecimal hash.
Join those records with one LF (`\n`), without a trailing newline, encode as UTF-8,
and compute SHA-256. The manifest order is part of the hash contract; sorting the
rows produces a different digest. `source_sha256` identifies this aggregate, not
an individual file.


- `plugins/agentic-actions-auditor/skills/agentic-actions-auditor/SKILL.md` (`80e36ab06e3ee667ac45bab036ed395fc425c4d54fa72c4b4981a5b982a389aa`)
- `plugins/ask-questions-if-underspecified/skills/ask-questions-if-underspecified/SKILL.md` (`fef9189249c46d08d5172f7010e0d83ae8dc104cc3d07714a909dd12f9e92e79`)
- `plugins/audit-context-building/skills/audit-context-building/SKILL.md` (`98e8d493f75456b7c7a5b6a4ad0b383e266ca5e550d3c627f5a4357fd1bf1cd2`)
- `plugins/building-secure-contracts/skills/algorand-vulnerability-scanner/SKILL.md` (`0ad3e96d8d58ce6c1678c114e884a5f84d21571160d424843747a5dcc8448957`)
- `plugins/building-secure-contracts/skills/audit-prep-assistant/SKILL.md` (`ea7db549ff26a57ebd101140dd8ed44434d5c91f3d91efc8927541bea8dd23e8`)
- `plugins/building-secure-contracts/skills/cairo-vulnerability-scanner/SKILL.md` (`e2e64b00cfcfe04eb915aee7bb00ddd0e74e9b4d0275bc0185b409965b05d60c`)
- `plugins/building-secure-contracts/skills/code-maturity-assessor/SKILL.md` (`10e55d278593a362a12451416f54bba7afb35a4a62001e35fe13a500f143e53f`)
- `plugins/building-secure-contracts/skills/cosmos-vulnerability-scanner/SKILL.md` (`5f12f1ecdcf220726d32b391e5e646807d09d869d4cc92ae105236ecff4b9a42`)
- `plugins/building-secure-contracts/skills/guidelines-advisor/SKILL.md` (`15b4864cd905a1ed1eea5f04b025b8326229c1c61e975338af77d794c0e84df7`)
- `plugins/building-secure-contracts/skills/secure-workflow-guide/SKILL.md` (`d4f765622ae684b7359427524f4db5eef184678dbfc8104026d248f5f0ebebe7`)
- `plugins/building-secure-contracts/skills/solana-vulnerability-scanner/SKILL.md` (`86f3a5e8572da69128745eb49043f47ab92f7e9adb7a715c6636099246e981c9`)
- `plugins/building-secure-contracts/skills/substrate-vulnerability-scanner/SKILL.md` (`611f69b419740b8f972eabc03b5cd88a38f0b07aeed755eae413629cabebb178`)
- `plugins/building-secure-contracts/skills/token-integration-analyzer/SKILL.md` (`f700683abe74bdd6d4107236c9a1a1ca625352412771131543b2a88af1a1ce94`)
- `plugins/building-secure-contracts/skills/ton-vulnerability-scanner/SKILL.md` (`3a0fbdedb1553bfaa41a81cf1d5ac4fb069aebd53483e3311122b8b2f8d288a2`)
- `plugins/burpsuite-project-parser/skills/burpsuite-project-parser/SKILL.md` (`43bf45e43192229810b5dab47d1eff3380db9cc86ed89374db87f9a869f19543`)
- `plugins/c-review/skills/c-review/SKILL.md` (`18fc634e6eaf60342d16500648da1c79e876297df9f32a3a798e9b449390fc44`)
- `plugins/claude-in-chrome-troubleshooting/skills/chrome-mcp-troubleshooting/SKILL.md` (`1456ace18266e81691c6ba0e5f3ec11df4a51cfa3e50eb511a113f15ab080c68`)
- `plugins/constant-time-analysis/skills/constant-time-analysis/SKILL.md` (`0ffc2357999f0fe4a8a11b347c99adf6db8310e199243c2f6b4398ce00d45346`)
- `plugins/culture-index/skills/interpreting-culture-index/SKILL.md` (`3c1fb19e51faf6643c2511d89e6fd1d185445ec5e8887bf97184468e99fed280`)
- `plugins/debug-buttercup/skills/debug-buttercup/SKILL.md` (`a8b043f5b6cc44657192f10fc6914a2f65402878e4a62eb7bd5e9bfe9b5e8e4f`)
- `plugins/devcontainer-setup/skills/devcontainer-setup/SKILL.md` (`ef698feec8a76cf89f283c07632a2ce92378cb34e030f6c2ca13f312a7393e39`)
- `plugins/differential-review/skills/differential-review/SKILL.md` (`1499d68ed4465fe89448f2bd90054b16a1a047f2e49a433623312f3b7a8a9742`)
- `plugins/dimensional-analysis/skills/dimensional-analysis/SKILL.md` (`0434b5ec95a0ae3037160e24d38d6579c3127ad86d0020e6f430d5f71c18c66b`)
- `plugins/dwarf-expert/skills/dwarf-expert/SKILL.md` (`5947233be70c9d7932f21082f5180dcdac1673eb0b3872e472aaab873217a04b`)
- `plugins/entry-point-analyzer/skills/entry-point-analyzer/SKILL.md` (`0d0e2956bdf9bf5be7efdfcefc754cabd2c1deb015731f3341f919eae2a0e3ca`)
- `plugins/firebase-apk-scanner/skills/firebase-apk-scanner/SKILL.md` (`fbd71e5f98ba9cf3b534dd764d511e4eb157fa50e09eb8e42accc78a61d9a838`)
- `plugins/fp-check/skills/fp-check/SKILL.md` (`129223b79b8cb1e7c289c90cbe4ba288d9b210e318a0d1464f319e30329481b3`)
- `plugins/gh-cli/skills/gh-cli/SKILL.md` (`3387cd7e38d10ddd9e67d88d69e180a7adefdb79b0d8b53d17640c0e408a3d2a`)
- `plugins/git-cleanup/skills/git-cleanup/SKILL.md` (`06bd0fe628ffa346cc7a59a4d3b7f765c2c4fcfeeeedca2da6728ff713afb19d`)
- `plugins/insecure-defaults/skills/insecure-defaults/SKILL.md` (`b1b95a2fa5b661a20c3812912f49d1063533dc7dbef726e70c9757424b6cdcbc`)
- `plugins/let-fate-decide/skills/let-fate-decide/SKILL.md` (`18abf9d7183fa8d5cf57130d84cf9ce8d200809406d32e260547d4d445863d0b`)
- `plugins/modern-python/skills/modern-python/SKILL.md` (`ef774b925eb1d1fc12e4f5ddc3f5ad925ecd795315827447228c70cc44c6170c`)
- `plugins/mutation-testing/skills/mutation-testing/SKILL.md` (`1bb6b5ddaf79d489047b2c3b8b319df4897c06221c12209dd1dfa7bce4b87f04`)
- `plugins/property-based-testing/skills/property-based-testing/SKILL.md` (`f482f34ce65ec8801f4ee64c645418c0be9876d19ba8f856a28e0548cd949ebd`)
- `plugins/rust-review/skills/rust-review/SKILL.md` (`84b002d6b42af8d66d6b0bcc2bba6d25383bd1c1fd58f4f6deca208488f12b5a`)
- `plugins/seatbelt-sandboxer/skills/seatbelt-sandboxer/SKILL.md` (`a6f960c96bbcb66a7cb83da76c6d73ad2acd87f41268774ed9ec01f0d3e78021`)
- `plugins/second-opinion/skills/second-opinion/SKILL.md` (`cdab9c8269c5198bfbde3f2db96a91af5a78ede8ab63a9c37778e9591090c0fc`)
- `plugins/semgrep-rule-creator/skills/semgrep-rule-creator/SKILL.md` (`6ca2e3b8520ed20af1b0879b7cab318832fcbe89c19c17a9fa347a45a9f28913`)
- `plugins/semgrep-rule-variant-creator/skills/semgrep-rule-variant-creator/SKILL.md` (`9308575e2b67bded99fdeaf222fc9da4d32f1044aff18a3dac4e83e073ebb883`)
- `plugins/sharp-edges/skills/sharp-edges/SKILL.md` (`3b69a709c2f8f0cfcf57d40a3186e166f307865cc8ed924be4098e549a121e9c`)
- `plugins/skill-improver/skills/skill-improver/SKILL.md` (`5002ddc4938950893c9f390927e5c1b480c0d1f54c1dd1ce695290fb91d90936`)
- `plugins/spec-to-code-compliance/skills/spec-to-code-compliance/SKILL.md` (`d92dff470c59ed35fabe8e88bc5058d67f4ac8e7f8686b3ed384ad13b254c0cf`)
- `plugins/static-analysis/skills/codeql/SKILL.md` (`b88b4f0b2044ed9abb7c42e6c2a0413ac66e5eb1a3a02fefe5c32725851fcd16`)
- `plugins/static-analysis/skills/sarif-parsing/SKILL.md` (`e3faaa40304dd8477d58793a9c8d34e63ec04c2dea5e13b0a26e48b0cdbbb3d1`)
- `plugins/static-analysis/skills/semgrep/SKILL.md` (`092472caba4d39701c3871418871b462098aa7d49c9c92ebdc8006b0d40fe548`)
- `plugins/supply-chain-risk-auditor/skills/supply-chain-risk-auditor/SKILL.md` (`9f978cffec0a13596e7047d80a7890d44457048be0700b44016b020a0980051f`)
- `plugins/testing-handbook-skills/skills/address-sanitizer/SKILL.md` (`5404e73526105c064eb051abe726097a9699ba39a2aaa23fb1b195d2835bd9c4`)
- `plugins/testing-handbook-skills/skills/aflpp/SKILL.md` (`4d49ad17437270cae03348a52f5b25d1f248b328981fd6a6c81fbd2b1fa6290b`)
- `plugins/testing-handbook-skills/skills/atheris/SKILL.md` (`54ffc20eacc05ef263085a5d17a49c93a8e6eb3499ad2f9ccbdcf86dae7baffe`)
- `plugins/testing-handbook-skills/skills/cargo-fuzz/SKILL.md` (`9474ddcfb3cae6aa65306fc9809523798f128dd68c5d4a327aacb82dfe385189`)
- `plugins/testing-handbook-skills/skills/constant-time-testing/SKILL.md` (`ddf883f5659af688370e82b0d58d1c7554d322d6566ce29aa493cc5735678061`)
- `plugins/testing-handbook-skills/skills/coverage-analysis/SKILL.md` (`9c98ce71f20970424a26ee28095f942d406b7c68135319e30eb47baac420ea00`)
- `plugins/testing-handbook-skills/skills/fuzzing-dictionary/SKILL.md` (`3247064b931fdc5b259e9d7786a7e50858cde27cedbf6bef873a5d77827efed8`)
- `plugins/testing-handbook-skills/skills/fuzzing-obstacles/SKILL.md` (`07b132241c8bd45c8b44d4cb5745f20a71ef6628fb5eecbf620217b1fe920c8a`)
- `plugins/testing-handbook-skills/skills/harness-writing/SKILL.md` (`6fb9ecf9cf3d8d7ed3246c50bac72181e2e7747794a2a121ccdf47a409d9f5ec`)
- `plugins/testing-handbook-skills/skills/libafl/SKILL.md` (`398d1a8313b479bd3d71229ac8f5da8447613f7adc28a9d596f22559074ed08b`)
- `plugins/testing-handbook-skills/skills/libfuzzer/SKILL.md` (`dc67b83f276991f6f7d3050119389af5a2bec70a1e8ceaa56ee875ddc0d233b4`)
- `plugins/testing-handbook-skills/skills/ossfuzz/SKILL.md` (`5ba74748ddc70989b9e61b471718791ddd5d39de5d72b3b5d60b0fee1b1fd3f2`)
- `plugins/testing-handbook-skills/skills/ruzzy/SKILL.md` (`603cde0d4592b4d4b81de645c05c7429969923dff290b4be2dd0b8614e2a6876`)
- `plugins/testing-handbook-skills/skills/testing-handbook-generator/SKILL.md` (`bb49c9516f4d714e0cc6b018ba01d9ec511a8b3ccb67ebd8a7a635a659f37911`)
- `plugins/testing-handbook-skills/skills/wycheproof/SKILL.md` (`f545b71bd68a8575c750af2cbe667703e9a40ae122bf298bbbe330e17b2d1271`)
- `plugins/trailmark/skills/audit-augmentation/SKILL.md` (`bee2b41fd11b830052f60fe5ae1fb2393a2a8c4e78995a372e55b36707de84e5`)
- `plugins/trailmark/skills/crypto-protocol-diagram/SKILL.md` (`11e665a8180bfc5dcac16cb4baa01100f83d6875b2d38dcd54ad6866f9b04dbc`)
- `plugins/trailmark/skills/diagramming-code/SKILL.md` (`af51a9ebad24b0a6255e92c286fa0143ef969fb5ffd6f3972f7667445a1a15cd`)
- `plugins/trailmark/skills/genotoxic/SKILL.md` (`ad54f0bc391c464db25e7094929285ed98b3bb924fd4fb00eacf950ff3771347`)
- `plugins/trailmark/skills/graph-evolution/SKILL.md` (`838cc7594d37bded9d0b240582ad44d94f52a899654d5fc7089f13f7fc377ba1`)
- `plugins/trailmark/skills/mermaid-to-proverif/SKILL.md` (`2f096151ad7fb5de2d74556bfa85322510a6e71710f4aa0ff963e5ce6ec3fa25`)
- `plugins/trailmark/skills/trailmark/SKILL.md` (`0e9dd2af9870dcddb6d0b4b5a87f04a74bb1bff4d6cac6bfdad74ebb163565b4`)
- `plugins/trailmark/skills/trailmark-structural/SKILL.md` (`1d17c27113cf69bbfb0162ffa49b0d5e351327a1d36c5aa190c6b0c39a983526`)
- `plugins/trailmark/skills/trailmark-summary/SKILL.md` (`47bf5fb07580fb65b66870d6828e7a6d9ef9e724762ae05476a98dd0139f2367`)
- `plugins/trailmark/skills/vector-forge/SKILL.md` (`e10842ca76aed8eaf3990f34e2d99934ea5bc756a062568993558e804b42695c`)
- `plugins/variant-analysis/skills/variant-analysis/SKILL.md` (`b0b94dec027087b25bae609a8104b496314b34c5095f474593597bac9639e333`)
- `plugins/workflow-skill-design/skills/designing-workflow-skills/SKILL.md` (`11fe6909d9a9be26d8d2d652dac19945e635081d936220cb84e264faeccbc278`)
- `plugins/yara-authoring/skills/yara-rule-authoring/SKILL.md` (`9e388dcf1a84add5e27f031e98139c960d59249530c0f4f413c42b58eed7e96a`)
- `plugins/zeroize-audit/skills/zeroize-audit/SKILL.md` (`cc21c714fa213902c1ba283fe3c6977a810ae1814a16892c0af0bc78dd69b4d0`)
