# Evidence

Screenshots and logs proving the build. Follow [architecture/cloud-architecture-lab.md](../architecture/cloud-architecture-lab.md) to produce them. The full list, with where to capture each one and what must be visible, is in [screenshot.md](../screenshot.md).

## Cloud Architecture Lab (Task 3)

- [ ] `lab-01-full-architecture.png`: complete canvas, every tier
- [ ] `lab-02-vpc-two-az.png`: VPC zoomed in: 2 AZs × public / app / data subnets
- [ ] `lab-03-flow-exam-autosave.png`: Walkthrough 1 simulated
- [ ] `lab-04-flow-upload-notify.png`: Walkthrough 2 simulated
- [ ] `lab-05-az-failure.png`: AZ A failed, Aurora reader promoted, flow still succeeds
- [ ] `lab-06-az-recovered.png`: AZ restored

## AWS deployment

- [ ] `aws-site-student.png`: student exam page showing the "Saved at …" autosave status
- [ ] `aws-upload-40mb.png`: upload progress / submission marked uploaded
- [ ] `aws-tutor-email.png`: new-submission email received by the tutor
- [ ] `aws-results-email.png`: results-released email
- [ ] `aws-rds-two-az.png`: RDS console showing Multi-AZ: primary and standby in different AZs
- [ ] `aws-dashboard.png`: CloudWatch dashboard
- [ ] `az-failover-*.log`: output of `scripts/simulate-az-failure.sh`
- [ ] `github-actions.png`: successful pipeline run triggered by a push to `main`
