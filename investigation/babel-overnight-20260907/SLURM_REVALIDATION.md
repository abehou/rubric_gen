# Slurm revalidation — 2026-09-07 20:36 EDT

Read-only evidence: the requested collab-forgetting analyze_cb9_base_swesmith_replication_cpu.sbatch uses cpu,4 CPUs,32G,48h and no account; other analysis scripts agree. No scientific conventions were imported.

Live sinfo and scontrol show partition cpu: cpu is absent. Site submission validation rejects zero-GPU requests for both cpu and general (the plugin reports a minimum-GPU error even for absent cpu). General has48h limit and normal QoS. Preempt is UP, default, permits preempt_cpu_qos and has31-day limit; this launcher conservatively keeps48h. sacctmgr lists user aydanh default accounting association dfried, but an explicit account is unnecessary. preempt_cpu_qos permits64 CPUs per user,32 per job and zero GPUs. normal allows8 GPUs per user.

Account-free sbatch --test-only --partition=preempt --qos=preempt_cpu_qos --cpus-per-task=32 --mem=256G --time=2-00:00:00 --wrap=true succeeds; its hypothetical job10351840 is not a submitted job. Chosen profile: one node/task,32 CPUs,256GiB,48h,zero GPUs,preempt/preempt_cpu_qos,no account directive. It is preemptible; native validated resume and persistent live sessions apply. Two such jobs fit the CPU-user ceiling, and all components still share aggregate60/one audit.

First scientific command: sbatch --parsable --job-name=rubric-dev3-smoke scripts/babel/dev3.sbatch smoke
After strict smoke coverage: sbatch --parsable --job-name=rubric-dev3-control scripts/babel/dev3.sbatch full
Result20 remains held until the user-setting baseline earns scale-up.
