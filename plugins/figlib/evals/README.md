# figlib plugin evals

Graders look at what Claude RAN or WROTE (tool_used on Bash/Write inputs), never regex over the whole
trace: the trace includes the skill text, which itself mentions figcheck/check_layout/export_svg, so a
trace regex passes without the tool ever running (smoke test 13567243). The one trace regex left,
'clean — no overflow', is check_layout's own output and appears in no skill.

Cases are realistic labmate requests; `_fixtures/` holds their input files, copied in by each case's
`scaffold.sh`. On Argo, run them through `scripts/20261118_figlib_plugin_eval_argo.sbatch` in the wuhrlab
repo (it sets up the sandbox's needs: socat, a node-local workspace, figlib on PATH, Chromium):

    sbatch scripts/20261118_figlib_plugin_eval_argo.sbatch --tag core            # with and without the plugin
    FIGLIB_ON_PATH=0 sbatch scripts/20261118_figlib_plugin_eval_argo.sbatch --tag not-installed
