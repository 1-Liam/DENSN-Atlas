// Extracted from tikv/raft-rs at commit aafb07c7bab439c6139926a77dfafc5b10e9bc84.
// Sources:
// - src/raft.rs
// - harness/tests/integration_cases/test_raft.rs
//
// This excerpt is kept only as provenance evidence for the real-world
// evaluation bundle.

impl Raft {
    /// Checks if logs are committed to its term.
    ///
    /// The check is useful usually when raft is leader.
    pub fn commit_to_current_term(&self) -> bool {
        self.raft_log
            .term(self.raft_log.committed)
            .is_ok_and(|t| t == self.term)
    }

    fn handle_read_index(&mut self) -> Result<()> {
        if !self.commit_to_current_term() {
            // Reject read only request when this leader has not committed any log entry
            // in its term.
            info!(
                self.logger,
                "leader has not yet committed in its term; dropping read index msg",
            );
            return Ok(());
        }
        Ok(())
    }
}

// `test_read_only_for_new_leader` ensures that a leader only accepts MsgReadIndex message
// when it commits at least one log entry at it term.
#[test]
fn test_read_only_for_new_leader() {
    // Drop MsgAppend to forbid peer 1 to commit any log entry at its term
    // after it becomes leader.
    // Force peer 1 to become leader
    // Ensure peer 1 drops read only request.
    nt.send(vec![new_message_with_entries(
        1,
        1,
        MessageType::MsgReadIndex,
        vec![new_entry(0, 0, Some("ctx"))],
    )]);
    // Force peer 1 to commit a log entry at its term.
    // Ensure peer 1 accepts read only request after it commits a entry at its term.
}
