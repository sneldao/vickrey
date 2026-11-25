// SPDX-License-Identifier: MIT
pragma solidity ^0.8.30;

/// @title RealityReceiptsEscrow
/// @notice Minimal fixed-bounty escrow for public-safe Reality Receipts challenges.
/// The contract records commitments and moves escrowed native QIE. It does not
/// decide whether evidence is true; the configured verifier/operator does that
/// off-chain under an explicit policy.
contract RealityReceiptsEscrow {
    enum ChallengeState {
        Open,
        Resolved,
        Refunded
    }

    enum Resolution {
        None,
        Accepted,
        Rejected,
        NoPayout
    }

    struct Challenge {
        address sponsor;
        uint256 amount;
        bytes32 criteriaHash;
        uint64 expiresAt;
        ChallengeState state;
        bytes32 submissionId;
        bytes32 commitmentHash;
        address observer;
        Resolution resolution;
        bytes32 proofHash;
        uint64 resolvedAt;
    }

    address public owner;
    address public operator;
    bool private _entered;

    mapping(bytes32 => Challenge) private challenges;

    event OperatorChanged(address indexed previousOperator, address indexed newOperator);
    event ChallengeCreated(
        bytes32 indexed challengeId,
        address indexed sponsor,
        uint256 amount,
        bytes32 criteriaHash,
        uint64 expiresAt
    );
    event EvidenceSubmitted(
        bytes32 indexed challengeId,
        bytes32 indexed submissionId,
        address indexed observer,
        bytes32 commitmentHash
    );
    event ChallengeResolved(
        bytes32 indexed challengeId,
        bytes32 indexed submissionId,
        Resolution resolution,
        bytes32 proofHash,
        address paidTo,
        uint256 amount
    );
    event ChallengeRefunded(bytes32 indexed challengeId, address indexed sponsor, uint256 amount);

    error NotOwner();
    error NotOperator();
    error Reentrant();
    error ZeroAddress();
    error ZeroAmount();
    error InvalidExpiry();
    error ChallengeExists();
    error ChallengeMissing();
    error ChallengeNotOpen();
    error ChallengeNotExpired();
    error SubmissionExists();
    error SubmissionMissing();
    error TransferFailed();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier onlyOperator() {
        if (msg.sender != operator) revert NotOperator();
        _;
    }

    modifier nonReentrant() {
        if (_entered) revert Reentrant();
        _entered = true;
        _;
        _entered = false;
    }

    constructor(address initialOperator) {
        if (initialOperator == address(0)) revert ZeroAddress();
        owner = msg.sender;
        operator = initialOperator;
        emit OperatorChanged(address(0), initialOperator);
    }

    function setOperator(address nextOperator) external onlyOwner {
        if (nextOperator == address(0)) revert ZeroAddress();
        emit OperatorChanged(operator, nextOperator);
        operator = nextOperator;
    }

    /// @notice Create a fixed-bounty challenge. The native token value is the escrow.
    /// Anyone may sponsor; resolution remains operator-controlled for this MVP.
    function createChallenge(
        bytes32 challengeId,
        bytes32 criteriaHash,
        uint64 expiresAt
    ) external payable {
        if (msg.value == 0) revert ZeroAmount();
        if (expiresAt <= block.timestamp) revert InvalidExpiry();
        if (challenges[challengeId].sponsor != address(0)) revert ChallengeExists();

        challenges[challengeId] = Challenge({
            sponsor: msg.sender,
            amount: msg.value,
            criteriaHash: criteriaHash,
            expiresAt: expiresAt,
            state: ChallengeState.Open,
            submissionId: bytes32(0),
            commitmentHash: bytes32(0),
            observer: address(0),
            resolution: Resolution.None,
            proofHash: bytes32(0),
            resolvedAt: 0
        });

        emit ChallengeCreated(challengeId, msg.sender, msg.value, criteriaHash, expiresAt);
    }

    /// @notice An observer wallet can bind its own evidence commitment to an open challenge.
    function submitEvidence(
        bytes32 challengeId,
        bytes32 submissionId,
        bytes32 commitmentHash
    ) external {
        _submitEvidence(challengeId, submissionId, commitmentHash, msg.sender);
    }

    /// @notice The operator can relay a submission for an observer authenticated off-chain.
    /// This is the hackathon MVP path; direct observer submission remains available.
    function submitEvidenceFor(
        bytes32 challengeId,
        bytes32 submissionId,
        bytes32 commitmentHash,
        address observer
    ) external onlyOperator {
        _submitEvidence(challengeId, submissionId, commitmentHash, observer);
    }

    /// @notice Resolve a challenge. Accepted pays the observer; every other resolution
    /// returns escrow to the sponsor while preserving the public resolution receipt.
    function resolveChallenge(
        bytes32 challengeId,
        Resolution resolution,
        bytes32 proofHash
    ) external onlyOperator nonReentrant {
        Challenge storage challenge = challenges[challengeId];
        if (challenge.sponsor == address(0)) revert ChallengeMissing();
        if (challenge.state != ChallengeState.Open) revert ChallengeNotOpen();
        if (resolution == Resolution.None) revert SubmissionMissing();
        if (resolution == Resolution.Accepted && challenge.observer == address(0)) {
            revert SubmissionMissing();
        }

        challenge.state = ChallengeState.Resolved;
        challenge.resolution = resolution;
        challenge.proofHash = proofHash;
        challenge.resolvedAt = uint64(block.timestamp);

        address paidTo;
        if (resolution == Resolution.Accepted) {
            paidTo = challenge.observer;
        } else {
            paidTo = challenge.sponsor;
        }
        uint256 amount = challenge.amount;
        _send(paidTo, amount);

        emit ChallengeResolved(
            challengeId,
            challenge.submissionId,
            resolution,
            proofHash,
            paidTo,
            amount
        );
    }

    /// @notice Return escrow after expiry when the operator never resolved the challenge.
    function refundExpired(bytes32 challengeId) external nonReentrant {
        Challenge storage challenge = challenges[challengeId];
        if (challenge.sponsor == address(0)) revert ChallengeMissing();
        if (challenge.state != ChallengeState.Open) revert ChallengeNotOpen();
        if (block.timestamp < challenge.expiresAt) revert ChallengeNotExpired();

        challenge.state = ChallengeState.Refunded;
        challenge.resolvedAt = uint64(block.timestamp);
        uint256 amount = challenge.amount;
        _send(challenge.sponsor, amount);

        emit ChallengeRefunded(challengeId, challenge.sponsor, amount);
    }

    function getChallenge(bytes32 challengeId) external view returns (Challenge memory) {
        return challenges[challengeId];
    }

    function _submitEvidence(
        bytes32 challengeId,
        bytes32 submissionId,
        bytes32 commitmentHash,
        address observer
    ) private {
        if (observer == address(0)) revert ZeroAddress();
        Challenge storage challenge = challenges[challengeId];
        if (challenge.sponsor == address(0)) revert ChallengeMissing();
        if (challenge.state != ChallengeState.Open) revert ChallengeNotOpen();
        if (block.timestamp >= challenge.expiresAt) revert InvalidExpiry();
        if (challenge.submissionId != bytes32(0)) revert SubmissionExists();

        challenge.submissionId = submissionId;
        challenge.commitmentHash = commitmentHash;
        challenge.observer = observer;

        emit EvidenceSubmitted(challengeId, submissionId, observer, commitmentHash);
    }

    function _send(address to, uint256 amount) private {
        (bool sent, ) = to.call{value: amount}("");
        if (!sent) revert TransferFailed();
    }
}
