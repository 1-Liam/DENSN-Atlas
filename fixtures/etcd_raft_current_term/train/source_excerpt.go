// Extracted from etcd-io/raft at commit bcec33429c39a8bade4c2472cc68cf6038a0664f.
// Sources:
// - raft.go
// - raft_paper_test.go
//
// This excerpt is kept only as provenance evidence for the real-world
// evaluation bundle.

package raft

// pendingReadIndexMessages is used to store messages of type MsgReadIndex
// that can't be answered as new leader didn't committed any log in
// current term. Those will be handled as fast as first log is committed in
// current term.

// committedEntryInCurrentTerm return true if the peer has committed an entry in its term.
func (r *raft) committedEntryInCurrentTerm() bool {
	return r.raftLog.zeroTermOnOutOfBounds(r.raftLog.term(r.raftLog.committed)) == r.Term
}

func releasePendingReadIndexMessages(r *raft) {
	if !r.committedEntryInCurrentTerm() {
		r.logger.Error("pending MsgReadIndex should be released only after first commit in current term")
		return
	}
}

// TestLeaderOnlyCommitsLogFromCurrentTerm tests that only log entries from the leader's
// current term are committed by counting replicas.
func TestLeaderOnlyCommitsLogFromCurrentTerm(t *testing.T) {
	// do not commit log entries in previous terms
	// commit log in current term
}
