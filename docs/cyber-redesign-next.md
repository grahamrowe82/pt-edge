# CyberEdge: What's Fixed, What's Still Wrong, and Why

## What we just fixed

Software scoring rewarded CVE volume. Chrome had 2,700 CVEs and scored 100/100 "critical-risk." Siemens medical firmware with 6 CVEs — all actively exploited — scored lower. The site was telling people Chrome is more dangerous than unpatched hospital equipment.

The fix: score products by the *proportion* of CVEs that are actually being exploited, not by how many exist. Chrome's 2,700 CVEs sound scary, but only 4% have high exploit probability. Siemens firmware has 6 CVEs and 100% are actively exploited. The new scoring reflects this: Chrome is low-risk, Siemens is critical.

We also redesigned CVE pages to lead with "Do I need to act?" — the question every visitor actually has — instead of an abstract score card.

## What's still wrong

### 1. "No confirmed fix" is usually wrong

**The problem.** We track whether a CVE has a known fix, but our data only covers 0.3% of CVEs. The other 99.7% show "No confirmed fix" — including CVEs that vendors patched years ago. Log4Shell, the xz-utils backdoor, Heartbleed: all show "no confirmed fix" on our site, which is false.

**Why it matters.** A developer looks up a CVE, sees "no confirmed fix," and either panics unnecessarily or (worse) loses trust in the site entirely. A security professional would instantly recognize this as bad data. Either way, we've failed.

**What it corrupts.** The CVE risk score has a "patch availability" dimension that gives 25 out of 25 points to every CVE where we lack fix data. That's 99.7% of all CVEs getting maximum risk for "no patch" when we simply don't know. It inflates every score by 25 points and adds zero information. The homepage section "Most Dangerous Unpatched CVEs" is also filtering on this — it's really showing "CVEs where we lack patch data," not "CVEs without patches."

**The fix.** Drop the patch_availability scoring dimension entirely until we have reliable data. Change the CVE detail page to say "Patch status unknown" instead of "No confirmed fix." Replace the homepage "unpatched" filter with a straight "highest exploit probability" list. Separately, investigate better patch data sources (OSV, vendor advisories, GitHub Security Advisories) as an ingest priority.

### 2. CVE count is not a danger signal

**The problem.** We show "Total CVEs: 2,702" for Chrome in the threat profile. A normal person reads this as "Chrome has 2,702 security problems." A security professional reads it as "Chrome is heavily audited by researchers, which is good."

**Why it matters.** Well-maintained popular software naturally accumulates more CVEs because more people look for bugs, and responsible vendors disclose and patch them. Having many CVEs is often a sign of a *healthy* security process, not a broken one. The Linux kernel has 11,000 CVEs and is the most trusted piece of software on earth. Showing the raw count without this context triggers false panic in exactly the audience we're trying to help.

**What to do.** Stop leading with absolute counts. The proportional bars (% of CVEs with high exploit probability, % on CISA KEV) already tell the real story. The total count can stay as secondary context but shouldn't be the headline number.

### 3. Average CVSS is meaningless for products

**The problem.** The threat profile shows "Avg CVSS: 7.6" for Chrome. A non-expert reads 7.6/10 as "really bad." A security professional knows that average CVSS across thousands of CVEs tells you nothing useful — it's like saying "the average severity of all bugs ever found in this product is high." So what?

**Why it matters.** CVSS is a theoretical severity rating assigned when a vulnerability is published. It measures "how bad could this be if exploited?" not "how likely is this to be exploited?" or "has this been patched?" A product where every CVE is quickly patched and rarely exploited can still have high average CVSS. Showing it suggests the product is dangerous when it isn't.

**What to do.** Remove avg CVSS from the product threat profile. It's already captured indirectly in the CVE-level scoring. At the product level, only exploitation signals (EPSS, KEV, Exploit-DB) reliably distinguish dangerous products from well-maintained ones.

### 4. Product scoring still uses CVSS and recency as dimensions

**The problem.** The current product scoring has four dimensions: Active Threat, Exploit Availability, Severity Profile (average CVSS), and Recency (age of latest CVE). The first two work — they measure observed exploitation. The last two are noise.

Severity Profile gives Chrome 19/25 because its CVEs are *rated* high severity. But almost none are exploited. A high CVSS rating with fast patching is a sign of good security practice, not bad.

Recency gives Chrome 25/25 because it had CVEs published this year. But recent CVEs in an actively maintained product mean researchers are finding bugs and the vendor is disclosing them — that's *good*. An abandoned product with no recent CVEs might actually be more dangerous because nobody's looking.

**Why it matters.** These two dimensions add 44 points of noise to Chrome's score, pushing it from 9 (low) to 53 (high). The score claims Chrome is "high-risk" when common sense and professional judgment both say it isn't. A CTO evaluating whether to use Chrome sees "high-risk" and makes a worse decision than if we'd shown nothing at all.

**The fix.** Drop both dimensions. Rescale Active Threat (0-50) and Exploitation Evidence (0-50) to fill the full 0-100 range. Tested results: Chrome drops to 21 (low), Windows Server 2012 stays at 71 (critical), Siemens firmware stays at 100 (critical). Only observed exploitation data, no theoretical noise.

### 5. Weakness and vendor scoring use MAX, not proportion

**The problem.** When we score a weakness type like CWE-79 (Cross-Site Scripting), we take the MAX severity and MAX exploitability across all linked CVEs. If even one XSS vulnerability is critical, the entire weakness type scores critical — even though 95% of XSS vulnerabilities are moderate.

Same for vendors: Microsoft scores critical on severity because it has at least one critical CVE. So does every other major vendor. The MAX operation destroys all differentiation.

**Why it matters.** A student trying to understand "how dangerous is XSS?" gets told it's critical-risk, which is misleading. XSS is common and usually moderate — there are critical cases but they're outliers. A security analyst comparing vendors sees them all clustered at the top because MAX compresses the range.

**What to do.** Migrate weakness and vendor scoring to the same proportion-based approach we're using for products. Instead of MAX(severity), use the proportion of linked CVEs with high EPSS, KEV listing, or public exploits. This is a bigger change (new materialized views) and should be its own PR.

## The epistemological principle

Every number on the site should answer a question a real person would ask. If it doesn't, it shouldn't be there.

A developer checking a CVE asks: "Do I need to act?" Not "what's the composite score?"
A CTO evaluating Chrome asks: "Is this safe?" Not "what's the average CVSS?"
A student learning about XSS asks: "How dangerous is this in practice?" Not "what's the max severity of any CVE ever linked to this CWE?"

The test for every metric: if a security professional and a layman would draw opposite conclusions from the same number, the number is wrong. Chrome scoring "high-risk" fails this test — the layman panics, the professional laughs, and neither is well-served.

## Priority order

1. **Fix product scoring dimensions** — drop CVSS + recency, keep exploitation signals only (this PR, needs MV update)
2. **Fix has_fix claims** — remove patch_availability from CVE scoring, change "No confirmed fix" to "Patch status unknown," fix homepage filter (small, next PR)
3. **Remove misleading stats** — drop avg CVSS from product profile, reframe CVE counts as context not headlines (template changes, next PR)
4. **Rewrite weakness + vendor scoring** — proportion-based like products (new MVs, separate PR)
5. **Better patch data** — investigate OSV/GHSA/vendor advisory ingest for real has_fix coverage (ingest work)
